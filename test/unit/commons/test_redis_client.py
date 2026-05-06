"""
Tests for RedisEREClient (ers.commons.adapters.redis_client).

Happy-path and round-trip tests use a short-lived Redis instance provided by
testcontainers (RedisContainer) via the shared ``redis_container`` and
``redis_client`` fixtures in ``tests/conftest.py``.

Failure-path tests (connection errors, close behaviour) use AsyncMock in place
of aioredis.Redis to avoid needing a real connection.
"""
import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as aioredis
from erspec.models.ere import (
    ClusterReference,
    EntityMention,
    EntityMentionIdentifier,
    EntityMentionResolutionRequest,
    EntityMentionResolutionResponse,
)
from redis.exceptions import ConnectionError as RedisConnectionError

from ers import config
from ers.commons.adapters.redis_client import (
    RedisConnectionConfig,
    RedisEREClient,
)


@pytest.fixture
def dummy_request() -> EntityMentionResolutionRequest:
    return EntityMentionResolutionRequest(
        ere_request_id="m1:01",
        timestamp=datetime(2026, 3, 1, 12, 34, 56, 123456, tzinfo=UTC),
        entity_mention=EntityMention(
            identifiedBy=EntityMentionIdentifier(
                request_id="m1",
                source_id="DEMO",
                entity_type="ORGANISATION",
            ),
            content="@prefix org: <http://www.w3.org/ns/org#> ...",
            content_type="text/turtle",
        ),
    )


@pytest.fixture
def dummy_response() -> EntityMentionResolutionResponse:
    return EntityMentionResolutionResponse(
        ere_request_id="m1:01",
        timestamp=datetime(2026, 3, 1, 12, 34, 56, 234567, tzinfo=UTC),
        entity_mention_id=EntityMentionIdentifier(
            request_id="m1",
            source_id="DEMO",
            entity_type="ORGANISATION",
        ),
        candidates=[ClusterReference(cluster_id="m1", confidence_score=0.0, similarity_score=0.0)],
    )


@pytest.fixture
def redis_ere_client(redis_client: aioredis.Redis) -> RedisEREClient:
    return RedisEREClient(config_or_client=redis_client)


@pytest.fixture
async def mock_ere_service(redis_client: aioredis.Redis, dummy_response: EntityMentionResolutionResponse):
    """Simulates the ERE: reads one request from the configured request channel,
    pushes a fixed response to the configured response channel."""
    _settings = config

    async def _serve():
        await redis_client.brpop(_settings.ERE_REQUEST_CHANNEL)
        await redis_client.lpush(_settings.ERE_RESPONSE_CHANNEL, dummy_response.model_dump_json())

    task = asyncio.create_task(_serve())
    yield
    if not task.done():
        task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


class TestPushThenPull:
    async def test_round_trip_returns_correct_response(
        self,
        redis_ere_client: RedisEREClient,
        mock_ere_service,
        dummy_request: EntityMentionResolutionRequest,
    ):
        await redis_ere_client.push_request(dummy_request)
        response = await redis_ere_client.pull_response()

        assert response.ere_request_id == dummy_request.ere_request_id
        assert len(response.candidates) == 1
        assert response.candidates[0].cluster_id == "m1"
        assert response.candidates[0].confidence_score == 0.0


class TestPullResponse:
    async def test_raises_timeout_when_no_message(self, redis_client: aioredis.Redis):
        client = RedisEREClient(config_or_client=redis_client, timeout=0.1)

        with pytest.raises(TimeoutError, match=config.ERE_RESPONSE_CHANNEL):
            await client.pull_response()

    async def test_raises_on_connection_error(self, redis_ere_client: RedisEREClient):
        redis_ere_client._redis_client.brpop = AsyncMock(side_effect=RedisConnectionError("boom"))

        with pytest.raises(ConnectionError):
            await redis_ere_client.pull_response()


class TestClose:
    async def test_skips_aclose_when_not_owner(self):
        mock_redis = AsyncMock(spec=aioredis.Redis)
        mock_redis.connection_pool = MagicMock()
        mock_redis.connection_pool.connection_kwargs = {}

        client = RedisEREClient(config_or_client=mock_redis)
        await client.close()

        mock_redis.aclose.assert_not_called()

    async def test_calls_aclose_when_owns_client(self):
        mock_redis = AsyncMock(spec=aioredis.Redis)

        with patch("ers.commons.adapters.redis_client.aioredis.Redis", return_value=mock_redis):
            client = RedisEREClient(config_or_client=RedisConnectionConfig.from_settings(config))

        await client.close()

        mock_redis.aclose.assert_called_once()

    async def test_logs_warning_on_aclose_failure(self, caplog):
        mock_redis = AsyncMock(spec=aioredis.Redis)
        mock_redis.aclose.side_effect = Exception("connection reset")

        with patch("ers.commons.adapters.redis_client.aioredis.Redis", return_value=mock_redis):
            client = RedisEREClient(config_or_client=RedisConnectionConfig.from_settings(config))

        with caplog.at_level(logging.WARNING):
            await client.close()

        assert "failed to close connection cleanly" in caplog.text
        assert not caplog.records[-1].exc_info  # exception was not re-raised


class TestPublishNotification:
    async def test_calls_redis_publish_with_correct_args(self):
        mock_redis = AsyncMock(spec=aioredis.Redis)
        mock_redis.connection_pool = MagicMock()
        mock_redis.connection_pool.connection_kwargs = {}
        mock_redis.publish = AsyncMock()
        client = RedisEREClient(config_or_client=mock_redis)

        await client.publish_notification("ers_notifications", "SRCIDrequestidORGANISATION")

        mock_redis.publish.assert_awaited_once_with("ers_notifications", "SRCIDrequestidORGANISATION")

    async def test_wraps_connection_error(self):
        mock_redis = AsyncMock(spec=aioredis.Redis)
        mock_redis.connection_pool = MagicMock()
        mock_redis.connection_pool.connection_kwargs = {}
        mock_redis.publish.side_effect = RedisConnectionError("boom")
        client = RedisEREClient(config_or_client=mock_redis)

        with pytest.raises(ConnectionError):
            await client.publish_notification("ers_notifications", "SRCIDrequestidORGANISATION")

    async def test_wraps_redis_timeout_error(self):
        """A redis.exceptions.TimeoutError must be translated to ConnectionError.

        Otherwise a network timeout during a Redis failover bubbles up as a
        redis.exceptions.* type that no caller catches, killing the integrator
        worker and silently losing the cross-instance signal.
        """
        from redis.exceptions import TimeoutError as RedisTimeoutError
        mock_redis = AsyncMock(spec=aioredis.Redis)
        mock_redis.connection_pool = MagicMock()
        mock_redis.connection_pool.connection_kwargs = {}
        mock_redis.publish.side_effect = RedisTimeoutError("timed out")
        client = RedisEREClient(config_or_client=mock_redis)

        with pytest.raises(ConnectionError):
            await client.publish_notification("ers_notifications", "k")


class TestContextManager:
    async def test_closes_on_normal_exit(self):
        mock_redis = AsyncMock(spec=aioredis.Redis)

        with patch("ers.commons.adapters.redis_client.aioredis.Redis", return_value=mock_redis):
            async with RedisEREClient(config_or_client=RedisConnectionConfig.from_settings(config)):
                pass

        mock_redis.aclose.assert_called_once()

    async def test_closes_on_exception(self):
        mock_redis = AsyncMock(spec=aioredis.Redis)

        with patch("ers.commons.adapters.redis_client.aioredis.Redis", return_value=mock_redis), pytest.raises(RuntimeError):
            async with RedisEREClient(config_or_client=RedisConnectionConfig.from_settings(config)):
                raise RuntimeError("something went wrong")

        mock_redis.aclose.assert_called_once()
