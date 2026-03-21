"""Unit tests for EREPublishService and the publish_request public API function."""
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from ers.commons.adapters.redis_client import AbstractClient
from ers.ere_contract_client.domain.errors import (
    ChannelUnavailableError,
    InvalidRequestError,
    MissingEntityMentionError,
    MissingEntityTypeError,
    MissingRequestIdError,
    MissingSourceIdError,
    RedisConnectionError,
    SerializationError,
)
from ers.ere_contract_client.services.ere_publish_service import (
    EREPublishService,
    publish_request,
)
from erspec.models.core import EntityMentionIdentifier
from erspec.models.ere import EntityMention, EntityMentionResolutionRequest


def make_request(
    source_id="SRC",
    request_id="REQ",
    entity_type="ORG",
    ere_request_id=None,
    timestamp=None,
    entity_mention=True,
) -> EntityMentionResolutionRequest:
    """Build a test request.

    Args:
        source_id: The source identifier for the entity mention triad.
        request_id: The request identifier for the entity mention triad.
        entity_type: The entity type for the entity mention triad.
        ere_request_id: Optional explicit request ID; empty string if None.
        timestamp: Optional explicit timestamp; None means absent.
        entity_mention: Pass True to build a default EntityMention, None to omit it.

    Returns:
        An EntityMentionResolutionRequest configured for testing.
    """
    if entity_mention is None:
        return EntityMentionResolutionRequest.model_construct(
            entity_mention=None,
            ere_request_id=ere_request_id or "",
        )
    return EntityMentionResolutionRequest(
        ere_request_id=ere_request_id or "",
        timestamp=timestamp,
        entity_mention=EntityMention(
            identifiedBy=EntityMentionIdentifier(
                source_id=source_id,
                request_id=request_id,
                entity_type=entity_type,
            ),
            content="some content",
            content_type="text/plain",
        ),
    )


@pytest.fixture
def mock_adapter() -> AbstractClient:
    """Return a mock AbstractClient with push_request as AsyncMock returning 1."""
    adapter = MagicMock(spec=AbstractClient)
    adapter.push_request = AsyncMock(return_value=1)
    adapter.request_channel_id = "ere_requests"
    return adapter


@pytest.fixture
def service(mock_adapter) -> EREPublishService:
    """Return an EREPublishService wired with the mock adapter."""
    return EREPublishService(adapter=mock_adapter)


class TestPublishRequestValidTriad:
    async def test_valid_request_calls_adapter(self, service, mock_adapter):
        """TC-012: valid request — adapter called, ere_request_id returned."""
        request = make_request()
        result = await service.publish_request(request)
        mock_adapter.push_request.assert_called_once_with(request)
        assert result is not None

    async def test_valid_request_returns_ere_request_id(self, service):
        """TC-012: explicit ere_request_id is returned unchanged."""
        request = make_request(ere_request_id="fixed-id")
        result = await service.publish_request(request)
        assert result == "fixed-id"


class TestPublishRequestMissingTriad:
    @pytest.mark.parametrize(
        "missing,expected_exc",
        [
            ("source_id", MissingSourceIdError),
            ("request_id", MissingRequestIdError),
            ("entity_type", MissingEntityTypeError),
        ],
    )
    async def test_raises_on_missing_triad_field(self, service, mock_adapter, missing, expected_exc):
        """TC-013: incomplete triad → specific InvalidRequestError subclass, adapter not called.

        Uses model_construct to bypass Pydantic validation so that falsy string
        values reach the service's _validate_triad check rather than being
        rejected during object construction.
        """
        triad_kwargs = {"source_id": "S", "request_id": "R", "entity_type": "ORG"}
        triad_kwargs[missing] = ""
        identifier = EntityMentionIdentifier.model_construct(**triad_kwargs)
        mention = EntityMention.model_construct(
            identifiedBy=identifier,
            content="some content",
            content_type="text/plain",
        )
        request = EntityMentionResolutionRequest.model_construct(
            entity_mention=mention,
            ere_request_id="",
        )
        with pytest.raises(expected_exc) as exc_info:
            await service.publish_request(request)
        assert exc_info.value.identifier is identifier
        mock_adapter.push_request.assert_not_called()

    async def test_raises_when_entity_mention_absent(self, service, mock_adapter):
        """TC-013: absent entity_mention → MissingEntityMentionError."""
        request = make_request(entity_mention=None)
        with pytest.raises(MissingEntityMentionError):
            await service.publish_request(request)
        mock_adapter.push_request.assert_not_called()


class TestPublishRequestMetadataAutoGeneration:
    async def test_auto_generates_ere_request_id_when_absent(self, service):
        """TC-014: missing ere_request_id → UUID4 auto-generated."""
        request = make_request(ere_request_id=None)
        result = await service.publish_request(request)
        assert result is not None
        parsed = uuid.UUID(result, version=4)
        assert str(parsed) == result

    async def test_preserves_existing_ere_request_id(self, service):
        """ere_request_id already set → not overwritten."""
        request = make_request(ere_request_id="my-id")
        result = await service.publish_request(request)
        assert result == "my-id"

    async def test_auto_sets_timestamp_when_absent(self, service):
        """TC-015: missing timestamp → current UTC set on request object."""
        before = datetime.now(UTC)
        request = make_request(timestamp=None)
        await service.publish_request(request)
        after = datetime.now(UTC)
        assert request.timestamp is not None
        assert before <= request.timestamp <= after

    async def test_preserves_existing_timestamp(self, service):
        """timestamp already set → not overwritten."""
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        request = make_request(timestamp=ts)
        await service.publish_request(request)
        assert request.timestamp == ts


class TestPublishRequestAdapterErrors:
    async def test_timeout_error_raises_channel_unavailable(self, service, mock_adapter):
        """TC-016: TimeoutError from adapter → ChannelUnavailableError."""
        mock_adapter.push_request = AsyncMock(side_effect=TimeoutError("queue full"))
        with pytest.raises(ChannelUnavailableError):
            await service.publish_request(make_request())

    async def test_connection_error_raises_redis_connection_error(self, service, mock_adapter):
        """TC-017: ConnectionError from adapter → RedisConnectionError."""
        mock_adapter.push_request = AsyncMock(side_effect=ConnectionError("refused"))
        with pytest.raises(RedisConnectionError):
            await service.publish_request(make_request())

    async def test_zero_push_raises_channel_unavailable(self, service, mock_adapter):
        """TC-018: adapter returns 0 (channel accepted nothing) → ChannelUnavailableError."""
        mock_adapter.push_request = AsyncMock(return_value=0)
        with pytest.raises(ChannelUnavailableError):
            await service.publish_request(make_request())


class TestPublishRequestSerializationError:
    async def test_serialization_failure_raises_serialization_error(self, service):
        """Pre-serialization failure → SerializationError before adapter is called."""
        identifier = make_request().entity_mention.identifiedBy
        # Inject a non-serializable value via model_construct to bypass Pydantic validation
        from erspec.models.core import EntityMentionIdentifier
        from erspec.models.ere import EntityMention

        bad_identifier = EntityMentionIdentifier.model_construct(
            source_id=object(),  # not JSON-serializable
            request_id="req",
            entity_type="ORG",
        )
        bad_mention = EntityMention.model_construct(
            identifiedBy=bad_identifier,
            content="c",
            content_type="text/plain",
        )
        from erspec.models.ere import EntityMentionResolutionRequest
        bad_request = EntityMentionResolutionRequest.model_construct(
            entity_mention=bad_mention,
            ere_request_id="pre-check",
        )
        with pytest.raises(SerializationError):
            await service.publish_request(bad_request)


class TestPublishRequestPublicApi:
    """Tests for the module-level publish_request public API function."""

    async def test_delegates_to_service_and_returns_ere_request_id(self, mock_adapter):
        """publish_request() wires adapter into EREPublishService and returns ere_request_id."""
        request = make_request(ere_request_id="pub-1")
        result = await publish_request(request, mock_adapter)
        assert result == "pub-1"
        mock_adapter.push_request.assert_called_once_with(request)

    async def test_propagates_invalid_request_error(self, mock_adapter):
        """publish_request() propagates InvalidRequestError from the service."""
        request = make_request(entity_mention=None)
        with pytest.raises(InvalidRequestError):
            await publish_request(request, mock_adapter)

    async def test_propagates_channel_unavailable_error(self, mock_adapter):
        """publish_request() propagates ChannelUnavailableError from the service."""
        mock_adapter.push_request = AsyncMock(return_value=0)
        with pytest.raises(ChannelUnavailableError):
            await publish_request(make_request(), mock_adapter)
