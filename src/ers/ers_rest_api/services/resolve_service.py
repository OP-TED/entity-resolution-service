from ers.ers_rest_api.domain.errors import ErrorCode, ErrorResponse
from ers.ers_rest_api.domain.resolution import (
    BulkResolveRequest,
    BulkResolveResponse,
    EntityMentionResolutionRequest,
    EntityMentionResolutionResult,
)
from ers.resolution_coordinator.services.resolution_coordinator_service import (
    ResolutionCoordinatorServiceABC,
)


class ResolveService:
    """Orchestrator for the POST /resolve and /resolve-bulk endpoints."""

    def __init__(self, resolution_coordinator: ResolutionCoordinatorServiceABC) -> None:
        self._coordinator = resolution_coordinator

    async def handle_resolve(
        self,
        request: EntityMentionResolutionRequest,
    ) -> EntityMentionResolutionResult:
        """Resolve an entity mention and return the cluster assignment."""
        return await self._coordinator.resolve(request.mention)

    async def handle_bulk_resolve(
        self,
        request: BulkResolveRequest,
    ) -> BulkResolveResponse:
        """Resolve multiple entity mentions, collecting per-item results."""
        results: list[EntityMentionResolutionResult] = []
        # TODO: replace with batch resolve method to resolution coordinator service once available
        for item in request.mentions:
            try:
                result = await self._coordinator.resolve(item.mention)
                results.append(result)
            except Exception:
                results.append(
                    EntityMentionResolutionResult(
                        identified_by=item.mention.identified_by,
                        error=ErrorResponse(
                            error_code=ErrorCode.SERVICE_ERROR,
                            detail=f"Failed to resolve mention ({item.mention.identified_by.source_id}, "
                            f"{item.mention.identified_by.request_id}, "
                            f"{item.mention.identified_by.entity_type})",
                        ),
                    )
                )
        return BulkResolveResponse(results=results)
