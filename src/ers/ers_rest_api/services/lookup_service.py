from ers.ers_rest_api.domain.data_transfer_objects import (
    LookupResponse,
)
from ers.ers_rest_api.services.exceptions import MentionNotFoundError
from ers.resolution_decision_store.services.resolution_decision_store_service import (
    ResolutionDecisionStoreServiceABC,
)


class LookupService:
    """Orchestrator for the GET /lookup endpoint."""

    def __init__(self, decision_store: ResolutionDecisionStoreServiceABC) -> None:
        self._decision_store = decision_store

    async def handle_lookup(
        self,
        source_id: str,
        request_id: str,
        entity_type: str,
    ) -> LookupResponse:
        """Look up the current cluster assignment for a mention triad."""
        decision = await self._decision_store.get_decision_for_mention(
            source_id=source_id,
            request_id=request_id,
            entity_type=entity_type,
        )

        if decision is None:
            raise MentionNotFoundError(source_id, request_id, entity_type)

        return LookupResponse(
            cluster_reference=decision.current_placement,
            last_updated=decision.updated_at or decision.created_at,
        )
