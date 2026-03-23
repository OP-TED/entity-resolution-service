"""Request Registry service — orchestrates registration, lookup, and snapshot management."""

import json
from datetime import UTC, datetime

from erspec.models.core import EntityMention, EntityMentionIdentifier

from ers.commons.adapters.hasher import ContentHasher
from ers.commons.adapters.tracing import trace_function
from ers.rdf_mention_parser.domain.rdf_mapping_config import RDFMappingConfig
from ers.rdf_mention_parser.services.mention_parser_service import parse_entity_mention
from ers.request_registry.adapters.records_repository import (
    MongoLookupStateRepository,
    MongoResolutionRequestRepository,
)
from ers.request_registry.domain.records import LookupRequestRecord, ResolutionRequestRecord
from ers.request_registry.services.exceptions import (
    IdempotencyConflictError,
    SnapshotRegressionError,
)


class RequestRegistryService:
    """Application service for the Request Registry use cases.

    All business logic lives here. The adapters only handle persistence and
    error wrapping — no business rules inside repositories.
    """

    def __init__(
        self,
        resolution_repo: MongoResolutionRequestRepository,
        lookup_repo: MongoLookupStateRepository,
        hasher: ContentHasher,
        rdf_config: RDFMappingConfig,
    ) -> None:
        self._resolution_repo = resolution_repo
        self._lookup_repo = lookup_repo
        self._hasher = hasher
        self._rdf_config = rdf_config

    async def register_resolution_request(
        self, entity_mention: EntityMention
    ) -> ResolutionRequestRecord:
        """Register an entity mention and return the stored record.

        - Empty content is rejected before any hashing or DB call.
        - Same triad + same hash → idempotent replay; existing record returned.
        - Same triad + different hash → IdempotencyConflictError.
        - New triad → parses RDF content, stores, and returns new record.
          Any parsing exception propagates to the caller unchanged.

        Args:
            entity_mention: The entity mention to register.

        Returns:
            The stored ResolutionRequestRecord (new or existing).

        Raises:
            ValueError: If content is empty.
            IdempotencyConflictError: If the triad exists with different content.
            ContentTooLargeError, UnsupportedEntityTypeError, MalformedRDFError,
            EntityTypeMismatchError, MultipleEntitiesFoundError, EmptyExtractionError:
                Propagated from the RDF parser on new registrations.
        """
        if not entity_mention.content:
            raise ValueError("entity_mention.content must not be empty.")

        content_hash = self._hasher.hash(entity_mention.content)
        identifier: EntityMentionIdentifier = entity_mention.identifiedBy

        existing = await self._resolution_repo.find_by_triad(identifier)
        if existing is not None:
            if existing.content_hash == content_hash:
                return existing
            raise IdempotencyConflictError(identifier)

        parsed = parse_entity_mention(entity_mention, self._rdf_config)
        record = ResolutionRequestRecord(
            **entity_mention.model_dump(exclude={"parsed_representation"}),
            content_hash=content_hash,
            received_at=datetime.now(UTC),
            parsed_representation=json.dumps(parsed),
        )
        return await self._resolution_repo.store(record)

    async def get_resolution_request(
        self, identifier: EntityMentionIdentifier
    ) -> ResolutionRequestRecord | None:
        """Return the stored record for a triad, or None if not found.

        Args:
            identifier: The triad (source_id, request_id, entity_type).

        Returns:
            The matching ResolutionRequestRecord, or None.
        """
        return await self._resolution_repo.find_by_triad(identifier)

    async def get_lookup_state(self, source_id: str) -> LookupRequestRecord | None:
        """Return the current snapshot state for a source, or None if unknown.

        Args:
            source_id: The source system identifier.

        Returns:
            The LookupRequestRecord for the source, or None if never advanced.
        """
        return await self._lookup_repo.get(source_id)

    async def advance_snapshot(
        self, source_id: str, snapshot_time: datetime
    ) -> LookupRequestRecord:
        """Advance the per-source snapshot marker to snapshot_time.

        Called after a bulk refresh response is successfully produced.
        Rejects time movement backwards or to the same point.

        Args:
            source_id: The source system identifier.
            snapshot_time: The new snapshot point. Must be strictly after the current one.

        Returns:
            The updated LookupRequestRecord.

        Raises:
            SnapshotRegressionError: If snapshot_time <= current last_snapshot.
        """
        current_state = await self._lookup_repo.get(source_id)
        if current_state is not None and snapshot_time <= current_state.last_snapshot:
            raise SnapshotRegressionError(
                source_id=source_id,
                current=current_state.last_snapshot,
                attempted=snapshot_time,
            )
        now = datetime.now(UTC)
        new_state = LookupRequestRecord(
            source_id=source_id,
            last_snapshot=snapshot_time,
            updated_at=now if now >= snapshot_time else snapshot_time,
        )
        return await self._lookup_repo.upsert(new_state)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@trace_function(span_name="request_registry.register_resolution")
async def register_resolution_request(
    entity_mention: EntityMention,
    service: RequestRegistryService,
) -> ResolutionRequestRecord:
    """Parse and register an entity mention as an immutable resolution request record.

    Args:
        entity_mention: The entity mention to register.
        service: The RequestRegistryService instance.

    Returns:
        The stored ResolutionRequestRecord (new or existing on idempotent replay).

    Raises:
        ValueError: If content is empty.
        IdempotencyConflictError: Same triad with different content.
        ContentTooLargeError, UnsupportedEntityTypeError, MalformedRDFError,
        EntityTypeMismatchError, MultipleEntitiesFoundError, EmptyExtractionError:
            From the RDF parser on new registrations.
    """
    return await service.register_resolution_request(entity_mention)


@trace_function(span_name="request_registry.get_resolution")
async def get_resolution_request(
    identifier: EntityMentionIdentifier,
    service: RequestRegistryService,
) -> ResolutionRequestRecord | None:
    """Retrieve a resolution request record by its triad.

    Args:
        identifier: The triad (source_id, request_id, entity_type).
        service: The RequestRegistryService instance.

    Returns:
        The matching ResolutionRequestRecord, or None.
    """
    return await service.get_resolution_request(identifier)


@trace_function(span_name="request_registry.get_lookup_state")
async def get_lookup_state(
    source_id: str,
    service: RequestRegistryService,
) -> LookupRequestRecord | None:
    """Return the current snapshot state for a source system.

    Args:
        source_id: The source system identifier.
        service: The RequestRegistryService instance.

    Returns:
        The LookupRequestRecord for the source, or None if never advanced.
    """
    return await service.get_lookup_state(source_id)


@trace_function(span_name="request_registry.advance_snapshot")
async def advance_snapshot(
    source_id: str,
    snapshot_time: datetime,
    service: RequestRegistryService,
) -> LookupRequestRecord:
    """Advance the per-source snapshot marker for bulk delta exposure.

    Args:
        source_id: The source system identifier.
        snapshot_time: The new snapshot point. Must be strictly after the current one.
        service: The RequestRegistryService instance.

    Returns:
        The updated LookupRequestRecord.

    Raises:
        SnapshotRegressionError: If snapshot_time <= current last_snapshot.
    """
    return await service.advance_snapshot(source_id, snapshot_time)
