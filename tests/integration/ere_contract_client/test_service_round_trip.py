"""Integration tests: EREPublishService round-trip with real Redis.

Uses testcontainers to spin up a Redis instance. Skips if Docker is unavailable.
"""

import pytest

from ers.commons.adapters.redis_client import ERE_REQUEST_CHANNEL_ID, RedisEREClient
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from erspec.models.core import EntityMentionIdentifier
from erspec.models.ere import EntityMention, EntityMentionResolutionRequest


@pytest.fixture
def ere_adapter(redis_client) -> RedisEREClient:
    """Return a RedisEREClient backed by the test container Redis client."""
    return RedisEREClient(config_or_client=redis_client)


@pytest.fixture
def service(ere_adapter) -> EREPublishService:
    """Return an EREPublishService wired to the test container adapter."""
    return EREPublishService(adapter=ere_adapter)


@pytest.fixture
def sample_request() -> EntityMentionResolutionRequest:
    """Return a minimal valid request with an empty ere_request_id for auto-generation."""
    return EntityMentionResolutionRequest(
        ere_request_id="",
        entity_mention=EntityMention(
            identifiedBy=EntityMentionIdentifier(
                source_id="TEDSWS",
                request_id="req-integ-001",
                entity_type="Organization",
            ),
            content="@prefix org: <http://www.w3.org/ns/org#> .",
            content_type="text/turtle",
        ),
    )


class TestPublishServiceRoundTrip:
    async def test_publish_puts_request_in_redis_list(
        self, service, redis_client, sample_request
    ):
        """After publish_request, the serialized request appears in the ere_requests list."""
        ere_request_id = await service.publish_request(sample_request)

        # Verify the request was pushed (lpush → read with rpop)
        raw = await redis_client.rpop(ERE_REQUEST_CHANNEL_ID)
        assert raw is not None, "Expected a message in the Redis list"

        # Deserialize and verify
        deserialized = EntityMentionResolutionRequest.model_validate_json(raw)
        assert deserialized.ere_request_id == ere_request_id
        assert deserialized.entity_mention.identifiedBy.source_id == "TEDSWS"
        assert deserialized.entity_mention.identifiedBy.request_id == "req-integ-001"

    async def test_publish_auto_generates_ere_request_id(
        self, service, redis_client, sample_request
    ):
        """Auto-generated ere_request_id is present and non-empty in published request."""
        assert sample_request.ere_request_id == ""  # confirm it starts as an empty string

        ere_request_id = await service.publish_request(sample_request)

        raw = await redis_client.rpop(ERE_REQUEST_CHANNEL_ID)
        deserialized = EntityMentionResolutionRequest.model_validate_json(raw)
        assert deserialized.ere_request_id == ere_request_id
        assert len(ere_request_id) > 0

    async def test_publish_auto_sets_timestamp(
        self, service, redis_client, sample_request
    ):
        """Auto-populated timestamp is present in published request bytes."""
        await service.publish_request(sample_request)

        raw = await redis_client.rpop(ERE_REQUEST_CHANNEL_ID)
        deserialized = EntityMentionResolutionRequest.model_validate_json(raw)
        assert deserialized.timestamp is not None
