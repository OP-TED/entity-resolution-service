from ers.ers_rest_api.domain.resolution import (
    EntityMentionResolutionRequest,
    EntityMentionResolutionResult,
)
from ers.resolution_coordinator.services.resolution_coordinator_service import (
    ResolutionCoordinatorServiceABC,
)


class ResolveService:
    """Orchestrator for the POST /resolve endpoint."""

    def __init__(self, resolution_coordinator: ResolutionCoordinatorServiceABC) -> None:
        self._coordinator = resolution_coordinator

    async def handle_resolve(
        self,
        request: EntityMentionResolutionRequest,
    ) -> EntityMentionResolutionResult:
        """Resolve an entity mention and return the cluster assignment."""
        return await self._coordinator.resolve(request.mention)
