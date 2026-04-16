"""EREPublishService: publishes EntityMentionResolutionRequests to Redis."""

import logging
import uuid
from datetime import UTC, datetime
from typing import cast

from erspec.models.ere import EntityMentionResolutionRequest

from ers.commons.adapters.redis_client import AbstractClient
from ers.commons.adapters.tracing import trace_function
from ers.ere_contract_client.domain.errors import (
    ChannelUnavailableError,
    MissingEntityMentionError,
    MissingEntityTypeError,
    MissingRequestIdError,
    MissingSourceIdError,
    RedisConnectionError,
    SerializationError,
)

log = logging.getLogger(__name__)


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

        try:
            count = await self._adapter.push_request(request)
        except TimeoutError as exc:
            raise ChannelUnavailableError(str(exc)) from exc
        except ConnectionError as exc:
            raise RedisConnectionError(str(exc)) from exc

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
        return cast(str, request.ere_request_id)

    def _validate_triad(self, request: EntityMentionResolutionRequest) -> None:
        """Raise InvalidRequestError if the correlation triad is incomplete.

        Args:
            request: The resolution request to validate.

        Raises:
            InvalidRequestError: If entity_mention is absent or any triad field is empty.
        """
        if request.entity_mention is None:
            raise MissingEntityMentionError()
        identifier = request.entity_mention.identifiedBy
        if not identifier.source_id:
            raise MissingSourceIdError(identifier)
        if not identifier.request_id:
            raise MissingRequestIdError(identifier)
        if not identifier.entity_type:
            raise MissingEntityTypeError(identifier)

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


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


@trace_function(span_name="ere_contract_client.publish")
async def publish_request(
    request: EntityMentionResolutionRequest,
    adapter: AbstractClient,
) -> str:
    """Validate, enrich, and publish an ERE resolution request.

    The public API entry point for publishing resolution requests to ERE.
    Span attributes are populated automatically via the extractor registered
    for ``EntityMentionResolutionRequest`` in
    ``ere_contract_client.adapters.span_extractors``.

    Args:
        request: The resolution request to publish.
        adapter: Redis adapter for the ERE channel.

    Returns:
        The ere_request_id (auto-generated if absent).

    Raises:
        InvalidRequestError: If the correlation triad is incomplete.
        SerializationError: If the request cannot be serialized.
        ChannelUnavailableError: If the Redis channel cannot accept the request.
        RedisConnectionError: If the Redis connection is refused or times out.
    """
    return await EREPublishService(adapter=adapter).publish_request(request)
