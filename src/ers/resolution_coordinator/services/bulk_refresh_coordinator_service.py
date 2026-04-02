"""BulkRefreshCoordinatorService — Spine C bulk cluster assignment refresh."""

import logging
from datetime import UTC, datetime

from erspec.models.core import Decision
from opentelemetry import trace

from ers.commons.adapters.tracing import trace_function
from ers.commons.domain.data_transfer_objects import CursorPage
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_coordinator.domain.exceptions import SourceNotFoundError
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

_log = logging.getLogger(__name__)


class BulkRefreshCoordinatorService:  # pylint: disable=too-few-public-methods
    """Application service for Spine C — bulk delta cluster assignment refresh.

    Retrieves all decisions that have changed for a source system since its
    last snapshot, advancing the snapshot marker after each successful page.

    Read-only invariant: never publishes to ERE or writes a Decision.
    The only write is advancing the per-source snapshot marker.
    """

    def __init__(
            self,
            registry_service: RequestRegistryService,
            decision_store_service: DecisionStoreService,
    ) -> None:
        self._registry_service = registry_service
        self._decision_store_service = decision_store_service

    async def refresh_bulk(
            self,
            source_id: str,
            cursor: str | None = None,
            page_size: int | None = None,
    ) -> CursorPage[Decision]:
        """Retrieve changed cluster assignments for a source since its last snapshot.

        Args:
            source_id: The source system identifier.
            cursor: Opaque pagination token from a previous response, or None for
                the first page.
            page_size: Max results per page. Capped by the Decision Store service.

        Returns:
            A CursorPage of Decisions updated since the last snapshot.

        Raises:
            SourceNotFoundError: If the source has no requests in the registry.
            RepositoryConnectionError: If the Decision Store is unavailable.
            SnapshotRegressionError: If the snapshot advances backwards (should not
                happen under normal single-caller usage).
        """
        exists = await self._registry_service.source_has_requests(source_id)
        if not exists:
            raise SourceNotFoundError(source_id)

        lookup_state = await self._registry_service.get_lookup_state(source_id)
        updated_since = lookup_state.last_snapshot if lookup_state else None

        page = await self._decision_store_service.query_decisions_delta(
            source_id=source_id,
            updated_since=updated_since,
            cursor=cursor,
            page_size=page_size,
        )

        if page.next_cursor is None:
            await self._registry_service.advance_snapshot(source_id, datetime.now(UTC))

        return page


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@trace_function(span_name="resolution_coordinator.refresh_bulk")
async def refresh_bulk(
        source_id: str,
        service: BulkRefreshCoordinatorService,
        cursor: str | None = None,
        page_size: int | None = None,
) -> CursorPage[Decision]:
    """Retrieve the delta of changed cluster assignments for a source.

    Args:
        source_id: The source system to query.
        service: The BulkRefreshCoordinatorService instance.
        cursor: Pagination cursor, or None for the first page.
        page_size: Max results per page.

    Returns:
        A CursorPage of Decisions updated since the last snapshot.

    Raises:
        SourceNotFoundError: If the source has no requests in the registry.
        RepositoryConnectionError: If the Decision Store is unavailable.
    """
    trace.get_current_span().set_attribute(
        "resolution_coordinator.source_id", source_id
    )
    return await service.refresh_bulk(source_id, cursor=cursor, page_size=page_size)
