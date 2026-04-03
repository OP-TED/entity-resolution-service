from datetime import UTC, datetime

from erspec.models.core import EntityMentionIdentifier

from ers.ers_rest_api.domain.lookup import (
    LookupResponse,
    RefreshBulkRequest,
    RefreshBulkResponse,
)
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService


class RefreshBulkService:
    """Orchestrator for the POST /refresh-bulk endpoint."""

    def __init__(
        self,
        decision_store: DecisionStoreService,
        registry: RequestRegistryService,
    ) -> None:
        self._decision_store = decision_store
        self._registry = registry

    async def handle_refresh_bulk(self, request: RefreshBulkRequest) -> RefreshBulkResponse:
        """Retrieve delta of changed assignments since the last synchronisation snapshot."""
        lookup_state = await self._registry.get_lookup_state(request.source_id)
        last_snapshot = lookup_state.last_snapshot if lookup_state else None

        page = await self._decision_store.query_decisions_by_timestamp(
            source_id=request.source_id,
            updated_since=last_snapshot,
            limit=request.limit,
            continuation_cursor=request.continuation_cursor,
        )

        deltas = [
            LookupResponse(
                identified_by=EntityMentionIdentifier(
                    source_id=d.about_entity_mention.source_id,
                    request_id=d.about_entity_mention.request_id,
                    entity_type=d.about_entity_mention.entity_type,
                ),
                cluster_reference=d.current_placement,
                last_updated=d.updated_at or d.created_at,
            )
            for d in page.results
        ]

        if page.next_cursor is None:
            await self._registry.advance_snapshot(
                request.source_id,
                datetime.now(UTC),
            )

        return RefreshBulkResponse(
            deltas=deltas,
            has_more=page.next_cursor is not None,
            continuation_cursor=page.next_cursor,
        )
