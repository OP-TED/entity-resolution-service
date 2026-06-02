"""Decision Store service — orchestrates decision persistence and cursor-paginated queries."""
import logging
from datetime import datetime

from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from opentelemetry import trace

from ers import config
from ers.commons.adapters.tracing import trace_function
from ers.commons.domain.data_transfer_objects import CursorPage, CursorParams
from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository
from ers.resolution_decision_store.domain.cluster_size_index import ClusterSizeIndex
from ers.resolution_decision_store.domain.outcome import is_same_outcome

_log = logging.getLogger(__name__)


class DecisionStoreService:
    """Application service for the Resolution Decision Store use cases."""

    def __init__(
        self,
        repository: MongoDecisionRepository,
        cluster_size_index: ClusterSizeIndex | None = None,
    ) -> None:
        """Initialise the service with its mandatory repository and optional index.

        Args:
            repository: The decision repository for persistence and queries.
            cluster_size_index: Optional per-cluster cardinality projection.
                When provided, ``store_decision`` maintains the index on every
                placement change.  ``None`` disables the hook (backward compat).
        """
        self._repository = repository
        self._cluster_size_index = cluster_size_index

    async def store_decision(
            self,
            identifier: EntityMentionIdentifier,
            current: ClusterReference,
            candidates: list[ClusterReference],
            updated_at: datetime,
    ) -> Decision:
        """Store or atomically replace a decision, short-circuiting on an unchanged outcome.

        The write is skipped (and the existing Decision returned unchanged) only
        when the incoming *outcome* is identical to the stored one — same
        ``current_placement`` **and** same (truncated) ``candidates``.  Any
        material change (cluster id, confidence, similarity, or candidate
        ordering) writes through and bumps ``updated_at`` so the decision
        re-surfaces for curator review.  A same-cluster confidence change is
        therefore *not* a no-op.

        Args:
            identifier: Entity mention triad for this decision.
            current: New cluster assignment.
            candidates: Pre-ordered candidate list from ERE.
            updated_at: Must be strictly greater than stored updated_at.

        Returns:
            The persisted Decision (existing one on no-op, newly stored on change).

        Raises:
            StaleOutcomeError: If stored updated_at >= incoming updated_at.
            RepositoryConnectionError: On MongoDB connection failure.
            RepositoryOperationError: On unexpected MongoDB error.
        """
        existing = await self._repository.find_by_triad(identifier)

        max_candidates = config.DECISION_STORE_MAX_CANDIDATES
        if len(candidates) > max_candidates:
            _log.warning(
                "Candidate list truncated",
                extra={"original": len(candidates), "max": max_candidates},
            )
        truncated_candidates = candidates[:max_candidates]

        if existing is not None and is_same_outcome(existing, current, truncated_candidates):
            _log.debug(
                "Outcome unchanged — short-circuiting write",
                extra={"cluster_id": current.cluster_id},
            )
            trace.get_current_span().set_attribute("decision_store.placement_unchanged", True)
            return existing

        # Pass existing so the repository skips its own pre-read (N2).
        # existing=None → insert path; existing=Decision → update path (R2 stale filter).
        decision = await self._repository.upsert_decision(
            identifier=identifier,
            current=current,
            candidates=truncated_candidates,
            updated_at=updated_at,
            existing=existing,
        )

        if self._cluster_size_index is not None:
            from_cluster = existing.current_placement.cluster_id if existing is not None else None
            await self._cluster_size_index.shift(
                from_cluster=from_cluster,
                to_cluster=current.cluster_id,
            )

        return decision

    async def get_decision_by_triad(
            self, identifier: EntityMentionIdentifier
    ) -> Decision | None:
        """Return the current decision for a triad, or None if not stored.

        Args:
            identifier: The entity mention triad.

        Returns:
            The matching Decision, or None.
        """
        return await self._repository.find_by_triad(identifier)

    async def query_decisions_paginated(
            self,
            cursor: str | None = None,
            page_size: int | None = None,
    ) -> CursorPage[Decision]:
        """Cursor-paginated traversal of all stored decisions (bulk sync mode).

        Args:
            cursor: Opaque pagination token from a previous response, or None for first page.
            page_size: Max results per page. Capped at DECISION_STORE_MAX_PAGE_SIZE.
                Defaults to DECISION_STORE_DEFAULT_PAGE_SIZE if None.

        Returns:
            A CursorPage with results and an optional next_cursor.

        Raises:
            InvalidCursorError: If the cursor string cannot be decoded.
        """
        effective_size = min(
            page_size if page_size is not None else config.DECISION_STORE_DEFAULT_PAGE_SIZE,
            config.DECISION_STORE_MAX_PAGE_SIZE,
        )
        return await self._repository.find_with_filters(
            filters=None,
            cursor_params=CursorParams(cursor=cursor, limit=effective_size),
        )

    async def query_decisions_delta(
            self,
            source_id: str,
            updated_since: datetime | None,
            cursor: str | None = None,
            page_size: int | None = None,
    ) -> CursorPage[Decision]:
        """Return decisions for a source updated after updated_since, paginated by cursor.

        Used by BulkRefreshCoordinatorService to compute the delta since the last
        snapshot for a given source system.

        Args:
            source_id: The source system identifier to filter by.
            updated_since: If provided, only decisions with updated_at > updated_since
                are returned. If None, all decisions for the source are returned
                (first-time lookup — source has no snapshot yet).
            cursor: Opaque pagination token from a previous response, or None for
                the first page.
            page_size: Max results per page. Capped at the system pagination limit.

        Returns:
            A CursorPage with matching Decisions and an optional next_cursor.

        Raises:
            InvalidCursorError: If the cursor string cannot be decoded.
            RepositoryConnectionError: On MongoDB connection failure.
        """
        effective_size = min(
            page_size if page_size is not None else config.DECISION_STORE_DEFAULT_PAGE_SIZE,
            config.DECISION_STORE_MAX_PAGE_SIZE,
        )
        return await self._repository.find_delta_for_source(
            source_id=source_id,
            updated_since=updated_since,
            cursor_params=CursorParams(cursor=cursor, limit=effective_size),
        )


# ── Public API (traced at the service boundary) ───────────────────────────────


@trace_function(span_name="decision_store.store_decision")
async def store_decision(
        identifier: EntityMentionIdentifier,
        current: ClusterReference,
        candidates: list[ClusterReference],
        updated_at: datetime,
        service: DecisionStoreService,
) -> Decision:
    """Store or atomically replace a resolution decision.

    Args:
        identifier: Entity mention triad for this decision.
        current: New cluster assignment.
        candidates: Pre-ordered candidate list from ERE.
        updated_at: Timestamp — must be strictly greater than stored updated_at.
        service: The DecisionStoreService instance.

    Returns:
        The persisted Decision.

    Raises:
        StaleOutcomeError: If stored updated_at >= incoming updated_at.
        RepositoryConnectionError: On MongoDB connection failure.
        RepositoryOperationError: On unexpected MongoDB error.
    """
    return await service.store_decision(identifier, current, candidates, updated_at)


@trace_function(span_name="decision_store.get_decision_by_triad")
async def get_decision_by_triad(
        identifier: EntityMentionIdentifier,
        service: DecisionStoreService,
) -> Decision | None:
    """Retrieve the current decision for an entity mention triad.

    Args:
        identifier: The entity mention triad.
        service: The DecisionStoreService instance.

    Returns:
        The matching Decision, or None.
    """
    return await service.get_decision_by_triad(identifier)


@trace_function(span_name="decision_store.query_paginated")
async def query_decisions_paginated(
        service: DecisionStoreService,
        cursor: str | None = None,
        page_size: int | None = None,
) -> CursorPage[Decision]:
    """Cursor-paginated traversal of all stored decisions for bulk sync.

    Args:
        service: The DecisionStoreService instance.
        cursor: Opaque pagination token, or None for first page.
        page_size: Max results per page. Capped at DECISION_STORE_MAX_PAGE_SIZE.

    Returns:
        A CursorPage with results and an optional next_cursor.

    Raises:
        InvalidCursorError: If the cursor string cannot be decoded.
    """
    return await service.query_decisions_paginated(cursor=cursor, page_size=page_size)


@trace_function(span_name="decision_store.query_delta")
async def query_decisions_delta(
        source_id: str,
        updated_since: datetime | None,
        service: DecisionStoreService,
        cursor: str | None = None,
        page_size: int | None = None,
) -> CursorPage[Decision]:
    """Return the delta of changed decisions for a source since a snapshot point.

    Args:
        source_id: The source system to query.
        updated_since: Lower-bound timestamp (exclusive). None means all decisions
            for the source (first-time lookup).
        service: The DecisionStoreService instance.
        cursor: Pagination cursor, or None for first page.
        page_size: Max results per page.

    Returns:
        A CursorPage of matching Decisions.

    Raises:
        InvalidCursorError: If the cursor is malformed.
        RepositoryConnectionError: On MongoDB connection failure.
    """
    return await service.query_decisions_delta(
        source_id=source_id,
        updated_since=updated_since,
        cursor=cursor,
        page_size=page_size,
    )
