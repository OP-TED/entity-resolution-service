"""Request Registry service — orchestrates registration, lookup, and snapshot management."""

from datetime import UTC, datetime

from erspec.models.core import EntityMention, EntityMentionIdentifier

from ers.commons.adapters.hasher import ContentHasher
from ers.request_registry.adapters.records_repository import (
    LookupRequestRepository,
    LookupStateRepository,
    ResolutionRequestRepository,
)
from ers.request_registry.domain.records import (
    LookupRequestRecord,
    LookupRequestType,
    LookupState,
    ResolutionRequestRecord,
)
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
        resolution_repo: ResolutionRequestRepository,
        lookup_repo: LookupStateRepository,
        lookup_request_repo: LookupRequestRepository,
        hasher: ContentHasher,
    ) -> None:
        self._resolution_repo = resolution_repo
        self._lookup_repo = lookup_repo
        self._lookup_request_repo = lookup_request_repo
        self._hasher = hasher

    async def register_resolution_request(
        self, entity_mention: EntityMention
    ) -> ResolutionRequestRecord:
        """Register an entity mention and return the stored record.

        - Empty content is rejected before any hashing or DB call.
        - Same triad + same hash → idempotent replay; existing record returned.
        - Same triad + different hash → IdempotencyConflictError.
        - New triad → stores and returns new record.
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

        record = ResolutionRequestRecord(
            identifier=identifier,
            entity_mention=entity_mention,
            content_hash=content_hash,
            received_at=datetime.now(UTC),
        )
        return await self._resolution_repo.store(record)

    async def get_resolution_request(
        self, identifier: EntityMentionIdentifier
    ) -> ResolutionRequestRecord | None:
        """Return the stored record for a triad, or None if not found."""
        return await self._resolution_repo.find_by_triad(identifier)

    async def list_resolution_requests_by_source(
        self, source_id: str, limit: int = 100, offset: int = 0
    ) -> list[ResolutionRequestRecord]:
        """Return a paginated list of records for a source."""
        return await self._resolution_repo.find_by_source_id(source_id, limit=limit, offset=offset)

    async def register_lookup_request(
        self, source_id: str, request_type: LookupRequestType
    ) -> LookupRequestRecord:
        """Register that a lookup was requested from a source (append-only).

        Always succeeds. Sets requested_at to the current UTC time.
        Multiple records per source_id are allowed — this is an audit log.
        """
        record = LookupRequestRecord(
            source_id=source_id,
            requested_at=datetime.now(UTC),
            request_type=request_type,
        )
        return await self._lookup_request_repo.store(record)

    async def get_lookup_state(self, source_id: str) -> LookupState | None:
        """Return the current LookupState for a source, or None if unknown."""
        return await self._lookup_repo.get(source_id)

    async def advance_snapshot(self, source_id: str, snapshot_time: datetime) -> LookupState:
        """Advance the per-source delta watermark to snapshot_time.

        Raises SnapshotRegressionError if snapshot_time <= current last_snapshot.
        """
        current_state = await self._lookup_repo.get(source_id)
        if current_state is not None and snapshot_time <= current_state.last_snapshot:
            raise SnapshotRegressionError(
                source_id=source_id,
                current=current_state.last_snapshot,
                attempted=snapshot_time,
            )
        now = datetime.now(UTC)
        new_state = LookupState(
            source_id=source_id,
            last_snapshot=snapshot_time,
            updated_at=now if now >= snapshot_time else snapshot_time,
        )
        return await self._lookup_repo.upsert(new_state)
