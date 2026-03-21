"""EREPublishService: publishes EntityMentionResolutionRequests to Redis."""

import contextlib
import logging
import uuid
from datetime import UTC, datetime

try:
    from opentelemetry import trace as _otel_trace

    tracer = _otel_trace.get_tracer(__name__)
    _otel_available = True
except ImportError:  # pragma: no cover - OTel not yet in project dependencies
    tracer = None
    _otel_available = False

from ers.commons.adapters.redis_client import AbstractClient
from ers.ere_contract_client.domain.errors import (
    ChannelUnavailableError,
    InvalidRequestError,
    RedisConnectionError,
    SerializationError,
)
from erspec.models.ere import EntityMentionResolutionRequest

log = logging.getLogger(__name__)

_ERR_ENTITY_MENTION_REQUIRED = "entity_mention is required"
_ERR_SOURCE_ID_REQUIRED = "source_id is required"
_ERR_REQUEST_ID_REQUIRED = "request_id is required"
_ERR_ENTITY_TYPE_REQUIRED = "entity_type is required"


@contextlib.asynccontextmanager
async def _span(name: str):
    """Yield an OTel span when available, or a no-op context otherwise."""
    if _otel_available and tracer is not None:
        with tracer.start_as_current_span(name) as span:
            yield span
    else:
        yield _NoOpSpan()


class _NoOpSpan:
    """Minimal no-op span used when OpenTelemetry is not installed."""

    def set_attribute(self, _key: str, _value: object) -> None:
        """No-op implementation."""

    def record_exception(self, _exc: Exception) -> None:
        """No-op implementation."""


class EREPublishService:
    """Service that validates and publishes ERE resolution requests.

    Args:
        adapter: An AbstractClient instance for pushing requests to Redis.
    """

    def __init__(self, adapter: AbstractClient) -> None:
        self._adapter = adapter

    async def publish_request(self, request: EntityMentionResolutionRequest) -> str:
        """Validate, enrich, and publish an ERE resolution request.

        Validates the correlation triad, auto-generates missing metadata,
        pre-serializes to catch failures early, then pushes the request to
        the Redis channel via the adapter.

        Note:
            Modifies ``request`` in place: auto-populates ``ere_request_id``
            and ``timestamp`` if absent before pushing.

        Args:
            request: The resolution request to publish.

        Returns:
            The ere_request_id (auto-generated if absent).

        Raises:
            InvalidRequestError: If the correlation triad is incomplete.
            SerializationError: If the request cannot be serialized.
            ChannelUnavailableError: If the Redis channel cannot accept the request.
            RedisConnectionError: If the Redis connection is refused or times out.
        """
        self._validate_triad(request)
        self._enrich_metadata(request)
        self._pre_serialize(request)

        async with _span("ere_contract_client.publish") as span:
            span.set_attribute("source_id", request.entity_mention.identifiedBy.source_id)
            span.set_attribute("request_id", request.entity_mention.identifiedBy.request_id)
            span.set_attribute("entity_type", request.entity_mention.identifiedBy.entity_type)
            span.set_attribute("ere_request_id", request.ere_request_id)

            try:
                count = await self._adapter.push_request(request)
            except TimeoutError as exc:
                span.record_exception(exc)
                raise ChannelUnavailableError(str(exc)) from exc
            except ConnectionError as exc:
                span.record_exception(exc)
                raise RedisConnectionError(str(exc)) from exc
            except (ChannelUnavailableError, RedisConnectionError) as exc:
                span.record_exception(exc)
                raise
            except Exception as exc:
                span.record_exception(exc)
                raise

            if count == 0:
                raise ChannelUnavailableError(
                    f"Channel '{self._adapter.request_channel_id}' accepted zero requests"
                )

        log.info(
            "ERE request published: source_id=%s request_id=%s entity_type=%s ere_request_id=%s",
            request.entity_mention.identifiedBy.source_id,
            request.entity_mention.identifiedBy.request_id,
            request.entity_mention.identifiedBy.entity_type,
            request.ere_request_id,
        )
        return request.ere_request_id

    def _validate_triad(self, request: EntityMentionResolutionRequest) -> None:
        """Raise InvalidRequestError if the correlation triad is incomplete.

        Args:
            request: The resolution request to validate.

        Raises:
            InvalidRequestError: If entity_mention is absent or any triad field is empty.
        """
        if request.entity_mention is None:
            raise InvalidRequestError(_ERR_ENTITY_MENTION_REQUIRED)
        identifier = request.entity_mention.identifiedBy
        if not identifier.source_id:
            raise InvalidRequestError(_ERR_SOURCE_ID_REQUIRED)
        if not identifier.request_id:
            raise InvalidRequestError(_ERR_REQUEST_ID_REQUIRED)
        if not identifier.entity_type:
            raise InvalidRequestError(_ERR_ENTITY_TYPE_REQUIRED)

    def _enrich_metadata(self, request: EntityMentionResolutionRequest) -> None:
        """Auto-populate ere_request_id and timestamp if absent.

        Args:
            request: The resolution request to enrich in-place.
        """
        if not request.ere_request_id:
            request.ere_request_id = str(uuid.uuid4())
        if request.timestamp is None:
            request.timestamp = datetime.now(UTC)

    def _pre_serialize(self, request: EntityMentionResolutionRequest) -> None:
        """Attempt serialization to catch failures before pushing to the channel.

        Args:
            request: The resolution request to validate serialization for.

        Raises:
            SerializationError: If the request cannot be serialized to JSON.
        """
        try:
            request.model_dump_json()
        except Exception as exc:
            raise SerializationError(
                f"Failed to serialize request {request.ere_request_id!r}: {exc}"
            ) from exc
