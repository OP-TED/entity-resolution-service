from erspec.models.core import EntityMention, EntityMentionIdentifier

from ers.ers_rest_api.domain.data_transfer_objects import (
    EntityMentionRequest,
    ResolveResponse,
)
from ers.resolution_coordinator.services.resolution_coordinator_service import (
    ResolutionCoordinatorServiceABC,
)


class ResolveService:
    """Orchestrator for the POST /resolve endpoint."""

    def __init__(self, resolution_coordinator: ResolutionCoordinatorServiceABC) -> None:
        self._coordinator = resolution_coordinator

    async def handle_resolve(self, request: EntityMentionRequest) -> ResolveResponse:
        """Resolve an entity mention and return the cluster assignment."""
        entity_mention = EntityMention(
            identifiedBy=EntityMentionIdentifier(
                source_id=request.source_id,
                request_id=request.request_id,
                entity_type=request.entity_type,
            ),
            content=request.content,
            content_type=request.content_type,
        )

        result = await self._coordinator.resolve(entity_mention)

        return ResolveResponse(
            canonical_entity_id=result.canonical_entity_id,
            status=result.outcome,
            request_id=result.request_id,
        )
