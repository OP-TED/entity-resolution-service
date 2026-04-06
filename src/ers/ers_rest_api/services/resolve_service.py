"""Orchestrator for the POST /resolve and /resolve-bulk endpoints."""

from erspec.models.core import Decision, EntityMentionIdentifier

from ers.commons.adapters.provisional_id import derive_provisional_cluster_id
from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.ers_rest_api.domain.errors import ErrorCode, ErrorResponse
from ers.ers_rest_api.domain.resolution import (
    BulkResolveRequest,
    BulkResolveResponse,
    EntityMentionResolutionRequest,
    EntityMentionResolutionResult,
)
from ers.resolution_coordinator.services.resolution_coordinator_service import (
    ResolutionCoordinatorService,
)


def _is_provisional(decision: Decision) -> bool:
    """Check whether a decision carries a provisional singleton ID."""
    expected = derive_provisional_cluster_id(decision.about_entity_mention)
    return bool(decision.current_placement.cluster_id == expected)


def _map_decision(decision: Decision) -> EntityMentionResolutionResult:
    """Map a coordinator Decision to the API response DTO."""
    return EntityMentionResolutionResult(
        identified_by=decision.about_entity_mention,
        canonical_entity_id=decision.current_placement.cluster_id,
        status=(
            ResolutionOutcome.PROVISIONAL
            if _is_provisional(decision)
            else ResolutionOutcome.CANONICAL
        ),
    )


def _map_error(
    identifier: EntityMentionIdentifier, exc: Exception
) -> EntityMentionResolutionResult:
    """Map a failed resolution to an error result DTO."""
    return EntityMentionResolutionResult(
        identified_by=identifier,
        error=ErrorResponse(
            error_code=ErrorCode.SERVICE_ERROR,
            detail=(
                f"Failed to resolve mention ({identifier.source_id}, "
                f"{identifier.request_id}, {identifier.entity_type}): {exc}"
            ),
        ),
    )


class ResolveService:
    """Orchestrator for the POST /resolve and /resolve-bulk endpoints."""

    def __init__(self, resolution_coordinator: ResolutionCoordinatorService) -> None:
        self._coordinator = resolution_coordinator

    async def handle_resolve(
        self,
        request: EntityMentionResolutionRequest,
    ) -> EntityMentionResolutionResult:
        """Resolve an entity mention and return the cluster assignment."""
        decision = await self._coordinator.resolve_single(request.mention)
        return _map_decision(decision)

    async def handle_bulk_resolve(
        self,
        request: BulkResolveRequest,
    ) -> BulkResolveResponse:
        """Resolve multiple entity mentions concurrently via the coordinator."""
        mentions = [item.mention for item in request.mentions]
        results = await self._coordinator.resolve_bulk(mentions)
        mapped: list[EntityMentionResolutionResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Decision):
                mapped.append(_map_decision(result))
            else:
                mapped.append(_map_error(mentions[i].identifiedBy, result))
        return BulkResolveResponse(results=mapped)
