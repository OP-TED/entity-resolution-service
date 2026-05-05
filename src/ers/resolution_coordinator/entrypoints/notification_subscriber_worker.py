"""Redis Pub/Sub subscriber background worker for cross-instance ERE outcome notification.

Lifecycle mirrors OutcomeIntegrationWorker:
- ``worker.start()`` schedules the run loop as a non-blocking asyncio.Task.
- ``await worker.stop()`` cancels and awaits the task.

The worker subscribes to a Redis Pub/Sub channel and calls
``waiter.notify(triad_key)`` for each message received, triggering any
``asyncio.Event`` waiting on that key in the local process.
"""
import asyncio
import logging
from typing import Protocol

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as _RedisLibConnectionError

from ers.commons.adapters.redis_client import RedisConnectionConfig

_log = logging.getLogger(__name__)

_BACKOFF_INITIAL = 1
_BACKOFF_CAP = 30


class TriadNotifier(Protocol):
    """Structural protocol satisfied by AsyncResolutionWaiter."""

    async def notify(self, triad_key: str) -> bool: ...


class NotificationSubscriberWorker:
    """Background worker that subscribes to a Redis Pub/Sub channel and
    forwards notifications to the local ``AsyncResolutionWaiter``.

    A dedicated Redis connection is created internally because ``SUBSCRIBE``
    puts a connection into pub/sub mode where no regular commands can run.

    Args:
        redis_config: Connection parameters for the dedicated subscriber connection.
        channel: Redis Pub/Sub channel name to subscribe to.
        waiter: Object satisfying ``TriadNotifier`` — ``AsyncResolutionWaiter``
            in production.
    """

    def __init__(
        self,
        redis_config: RedisConnectionConfig,
        channel: str,
        waiter: TriadNotifier,
    ) -> None:
        self._redis_config = redis_config
        self._channel = channel
        self._waiter = waiter
        self._task: asyncio.Task | None = None
        self._subscribed = asyncio.Event()

    @property
    def subscribed(self) -> asyncio.Event:
        """Set once the first SUBSCRIBE handshake with Redis completes.

        Useful in tests and health-check probes to avoid polling with a bare sleep.
        """
        return self._subscribed

    def start(self) -> asyncio.Task:
        """Schedule ``run()`` as a non-blocking background asyncio.Task.

        Returns:
            The running ``asyncio.Task``.
        """
        self._task = asyncio.create_task(self.run(), name="notification_subscriber_worker")
        return self._task

    async def stop(self) -> None:
        """Cancel the background task and await clean termination.

        Safe to call even if ``start()`` was never called or the task has
        already finished.
        """
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._subscribed.clear()

    async def run(self) -> None:
        """Pub/Sub listen loop with exponential backoff reconnect.

        Calls ``waiter.notify(triad_key)`` for each ``message``-type frame.
        Reconnects automatically after ``redis.exceptions.ConnectionError`` using
        exponential backoff (1 s - 2 s - 4 s, capped at 30 s). Propagates
        ``CancelledError`` for clean shutdown.
        """
        _log.info("NotificationSubscriberWorker started on channel '%s'", self._channel)
        backoff = _BACKOFF_INITIAL
        try:
            while True:
                redis_client = aioredis.Redis(**self._redis_config.to_redis_kwargs())
                pubsub = redis_client.pubsub()
                try:
                    await pubsub.subscribe(self._channel)
                    self._subscribed.set()
                    _log.info(
                        "NotificationSubscriberWorker connected, subscribed to '%s'",
                        self._channel,
                    )
                    async for message in pubsub.listen():
                        backoff = _BACKOFF_INITIAL  # reset only once messages flow
                        if message["type"] != "message":
                            continue
                        try:
                            triad_key = message["data"].decode("utf-8")
                        except (UnicodeDecodeError, AttributeError):
                            _log.warning(
                                "NotificationSubscriberWorker: invalid payload, skipping: %r",
                                message.get("data"),
                            )
                            continue
                        _log.debug("Cross-instance notification received for triad '%s'", triad_key)
                        owned = await self._waiter.notify(triad_key)
                        if owned:
                            _log.debug("Triad '%s': local waiter found and unblocked", triad_key)
                        else:
                            _log.debug("Triad '%s': not owned by this instance, notification discarded", triad_key)
                    break  # listen() exhausted normally (tests / graceful shutdown)
                except _RedisLibConnectionError as exc:
                    self._subscribed.clear()
                    _log.warning(
                        "NotificationSubscriberWorker lost connection: %s - retrying in %ds",
                        exc,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _BACKOFF_CAP)
                finally:
                    # Two-phase cleanup. Each leg swallows ordinary Exceptions but
                    # not BaseException, so CancelledError still propagates. The
                    # outer try/finally guarantees aclose runs even when the first
                    # await is cancelled mid-flight, preventing a connection leak
                    # on shutdown.
                    try:
                        try:
                            await asyncio.shield(pubsub.unsubscribe(self._channel))
                        except Exception:  # noqa: BLE001 — best-effort cleanup
                            pass
                    finally:
                        try:
                            await asyncio.shield(redis_client.aclose())
                        except Exception:  # noqa: BLE001 — best-effort cleanup
                            pass
        except asyncio.CancelledError:
            _log.info("NotificationSubscriberWorker stopped")
            raise
