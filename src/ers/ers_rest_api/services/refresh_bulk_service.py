from datetime import UTC, datetime

from erspec.models.core import EntityMentionIdentifier

from ers.ers_rest_api.domain.lookup import (
    LookupResponse,
    RefreshBulkRequest,
    RefreshBulkResponse,
)
from ers.resolution_decision_store.services.resolution_decision_store_service import (
    ResolutionDecisionStoreServiceABC,
)


class RefreshBulkService:
    """Orchestrator for the POST /refresh-bulk endpoint."""

    def __init__(self, decision_store: ResolutionDecisionStoreServiceABC) -> None:
        self._decision_store = decision_store

    async def handle_refresh_bulk(self, request: RefreshBulkRequest) -> RefreshBulkResponse:
        """Retrieve delta of changed assignments since the last synchronisation snapshot."""
        lookup_state = await self._decision_store.get_lookup_state(request.source_id)
        last_snapshot = lookup_state.last_snapshot if lookup_state else None

        page = await self._decision_store.get_delta_for_source(
            source_id=request.source_id,
            last_snapshot=last_snapshot,
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
            for d in page.deltas
        ]

        await self._decision_store.advance_snapshot(
            request.source_id,
            datetime.now(UTC),
        )

        return RefreshBulkResponse(
            deltas=deltas,
            has_more=page.has_more,
            continuation_cursor=page.continuation_cursor,
        )
