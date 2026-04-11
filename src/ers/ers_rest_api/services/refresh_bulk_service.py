"""Orchestrator for the POST /refresh-bulk endpoint."""

from erspec.models.core import Decision

from ers.ers_rest_api.domain.lookup import (
    LookupResponse,
    RefreshBulkRequest,
    RefreshBulkResponse,
)
from ers.request_registry.domain.records import TriadKey
from ers.request_registry.services.request_registry_service import (
    RequestRegistryService,
    get_contexts_for_triads,
)
from ers.resolution_coordinator.services.bulk_refresh_coordinator_service import (
    BulkRefreshCoordinatorService,
)


class RefreshBulkService:  # pylint: disable=too-few-public-methods
    """Orchestrator for the POST /refresh-bulk endpoint.

    Delegates to BulkRefreshCoordinatorService (Spine C) and maps
    the CursorPage[Decision] result to the REST API response DTO,
    enriching each delta with the context from the request registry.
    """

    def __init__(
        self,
        bulk_coordinator: BulkRefreshCoordinatorService,
        registry_service: RequestRegistryService,
    ) -> None:
        self._coordinator = bulk_coordinator
        self._registry_service = registry_service

    async def handle_refresh_bulk(self, request: RefreshBulkRequest) -> RefreshBulkResponse:
        """Retrieve delta of changed assignments since the last synchronisation snapshot."""
        page = await self._coordinator.refresh_bulk(
            source_id=request.source_id,
            cursor=request.continuation_cursor,
            page_size=request.limit,
        )

        identifiers = [d.about_entity_mention for d in page.results]
        contexts = await get_contexts_for_triads(identifiers, self._registry_service)

        def _ctx(d: Decision) -> str | None:
            return contexts.get(TriadKey.from_identifier(d.about_entity_mention))

        deltas = [
            LookupResponse(
                identified_by=d.about_entity_mention,
                cluster_reference=d.current_placement,
                last_updated=d.updated_at or d.created_at,
                context=_ctx(d),
            )
            for d in page.results
        ]

        return RefreshBulkResponse(
            deltas=deltas,
            has_more=page.next_cursor is not None,
            continuation_cursor=page.next_cursor,
        )
