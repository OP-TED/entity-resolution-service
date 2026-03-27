import logging
from abc import ABC, abstractmethod

import redis.asyncio as aioredis
from erspec.models.ere import ERERequest, EREResponse
from redis.exceptions import ConnectionError as _RedisLibConnectionError

from ers.commons.adapters.redis_messages import get_response_from_message

log = logging.getLogger(__name__)


class RedisConnectionConfig:
    """Simple data class to hold Redis connection configuration."""

    def __init__(self, host: str, port: int, db: int):
        self.host = host
        self.port = port
        self.db = db

    @classmethod
    def from_settings(cls, settings) -> "RedisConnectionConfig":
        """Construct a RedisConnectionConfig from application settings.

        Args:
            settings: Application settings instance (ERSConfigResolver or compatible).

        Returns:
            A RedisConnectionConfig populated from settings.
        """
        return cls(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB)

    def __str__(self) -> str:
        return (
            f'RedisConnectionConfig ( host: "{self.host}", port: "{self.port}", db: "{self.db}" )'
        )


class AbstractClient(ABC):
    """Abstraction of a client to access with an ERS instance."""

    @abstractmethod
    async def push_request(self, request: ERERequest) -> int:
        """Push a request onto the request channel.

        Args:
            request: The ERE request to serialize and enqueue.

        Returns:
            The length of the list after the push (0 means the channel did not accept the request).

        Raises:
            ConnectionError: If the underlying transport cannot reach the channel.
        """

    @abstractmethod
    async def pull_response(self) -> EREResponse:
        """Pull the next response from the response channel.

        Blocks until a message is available or the timeout expires.

        Returns:
            The next EREResponse from the channel.

        Raises:
            TimeoutError: If a timeout is configured and no response arrives in time.
            ConnectionError: On connection failure.
        """

    @abstractmethod
    async def ping(self) -> bool:
        """Check if the underlying transport is reachable.

        Returns:
            True if the channel is reachable, False otherwise.
        """

    @abstractmethod
    async def close(self) -> None:
        """Close the underlying connection and release resources."""

    async def __aenter__(self) -> "AbstractClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()


class RedisEREClient(AbstractClient):
    """A simple ERS client that interacts with a Redis queue."""

    def __init__(
        self,
        config_or_client: RedisConnectionConfig | aioredis.Redis,
        timeout: float = 0,
        request_channel: str = "ere_requests",
        response_channel: str = "ere_responses",
    ):
        """Initialise the Redis ERE client.

        Args:
            config_or_client: A RedisConnectionConfig to create a new connection
                (owned and closed by this client), or an existing aioredis.Redis
                instance to reuse (caller retains ownership and must close it).
            timeout: Maximum seconds to wait for a response in pull_response().
                0 (default) blocks indefinitely.
            request_channel: Redis list key for outbound requests.
                Defaults to "ere_requests"; real callers should pass
                ``settings.ere_request_channel``.
            response_channel: Redis list key for inbound responses.
                Defaults to "ere_responses"; real callers should pass
                ``settings.ere_response_channel``.
        """
        if isinstance(config_or_client, RedisConnectionConfig):
            self.config = config_or_client
            log.info("Redis ERE client: connecting to %s", self.config)
            self._redis_client = aioredis.Redis(
                host=self.config.host, port=self.config.port, db=self.config.db
            )
        else:
            log.info("Redis ERE client: using existing redis client #%s", id(config_or_client))
            conn_args = config_or_client.connection_pool.connection_kwargs
            log.debug(
                "Redis client config: host=%s, port=%s, db=%s, unix_socket_path=%s",
                conn_args.get("host"),
                conn_args.get("port"),
                conn_args.get("db"),
                conn_args.get("unix_socket_path"),
            )
            self._redis_client = config_or_client

        self.character_encoding = "utf-8"
        self.request_channel_id = request_channel
        self.response_channel_id = response_channel
        self._owns_client = isinstance(config_or_client, RedisConnectionConfig)
        self.timeout = timeout
        if timeout:
            log.debug("Redis ERE client: pull_response() timeout set to %ss", timeout)
        else:
            log.debug("Redis ERE client: pull_response() timeout not set, blocking indefinitely")

    async def push_request(self, request: ERERequest) -> int:
        """Push a request onto the request channel identified by ERE_REQUEST_CHANNEL_ID.

        Args:
            request: The ERE request to serialize and enqueue.

        Returns:
            The length of the list after the push (0 means the channel did not accept the request).

        Raises:
            ConnectionError: If the Redis connection is refused or unavailable.
        """
        log.debug(
            "Redis ERE client, pushing request id: %s to channel: %s",
            request.ere_request_id,
            self.request_channel_id,
        )
        try:
            msg_json_str = request.model_dump_json()
            count = await self._redis_client.lpush(self.request_channel_id, msg_json_str)
        except _RedisLibConnectionError as exc:
            raise ConnectionError(str(exc)) from exc
        log.debug("Redis ERE client, request id: %s sent", request.ere_request_id)
        return count

    async def pull_response(self) -> EREResponse:
        """Pull the next response from the response channel identified by ERE_RESPONSE_CHANNEL_ID.

        Blocks until a message is available or the configured timeout expires.

        Returns:
            The next EREResponse from the channel.

        Raises:
            TimeoutError: If no response arrives within the configured timeout.
            redis.exceptions.ConnectionError: On connection failure.
        """
        log.debug(
            "Redis ERE client, waiting for response on channel: %s",
            self.response_channel_id,
        )
        try:
            result = await self._redis_client.brpop(self.response_channel_id, timeout=self.timeout)
        except _RedisLibConnectionError as ex:
            log.error("Redis ERE client, pull_response() failed due to connection issue: %s", ex)
            raise ConnectionError(str(ex)) from ex
        if result is None:
            raise TimeoutError(
                f"No response received on channel '{self.response_channel_id}' within {self.timeout}s"
            )
        _, raw_msg = result
        response = get_response_from_message(raw_msg, self.character_encoding)
        log.debug("Redis ERE client, received response id: %s", response.ere_request_id)
        return response

    async def ping(self) -> bool:
        """Check if the Redis server is reachable.

        Returns:
            True if the server responded to PING, False on any error.
        """
        try:
            result = await self._redis_client.ping()
            return bool(result)
        except Exception:
            return False

    async def close(self) -> None:
        """Close the connection if owned by this client; no-op otherwise.

        Logs a warning if closing fails but does not raise, so callers
        (including context manager ``__aexit__``) are never interrupted by
        cleanup errors.
        """
        if not self._owns_client:
            log.debug("Redis ERE client: connection not owned, skipping close")
            return
        try:
            log.info("Redis ERE client: closing connection")
            await self._redis_client.aclose()
        except Exception as ex:
            log.warning("Redis ERE client: failed to close connection cleanly: %s", ex)
