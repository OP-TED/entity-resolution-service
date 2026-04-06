from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.ers_rest_api.domain.errors import ErrorResponse
from ers.ers_rest_api.domain.resolution import (
    BulkResolveRequest,
    BulkResolveResponse,
    EntityMentionResolutionRequest,
    EntityMentionResolutionResult,
)
from ers.ers_rest_api.entrypoints.api.dependencies import get_resolve_service
from ers.ers_rest_api.services import ResolveService

router = APIRouter(tags=["Resolution"])


@router.post(
    "/resolve",
    responses={
        200: {"description": "Canonical resolution"},
        202: {"description": "Provisional resolution"},
        400: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def resolve(
    request: EntityMentionResolutionRequest,
    response: Response,
    service: Annotated[ResolveService, Depends(get_resolve_service)],
) -> EntityMentionResolutionResult:
    """Resolve an entity mention and return canonical or provisional cluster ID."""
    result = await service.handle_resolve(request)
    if result.status == ResolutionOutcome.PROVISIONAL:
        response.status_code = status.HTTP_202_ACCEPTED
    return result


def _bulk_status_code(result: BulkResolveResponse) -> int:
    """Derive the envelope HTTP status from per-item outcomes.

    Returns:
        200 — all results are canonical.
        202 — all results are provisional.
        207 — mixed outcomes (canonical + provisional, or any errors).
    """
    statuses = {r.status for r in result.results}
    has_errors = any(r.error is not None for r in result.results)
    if has_errors or len(statuses) > 1:
        return status.HTTP_207_MULTI_STATUS
    if statuses == {ResolutionOutcome.PROVISIONAL}:
        return status.HTTP_202_ACCEPTED
    return status.HTTP_200_OK


@router.post(
    "/resolve-bulk",
    responses={
        200: {"description": "All canonical"},
        202: {"description": "All provisional"},
        207: {"description": "Mixed outcomes"},
        400: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def resolve_bulk(
    request: BulkResolveRequest,
    response: Response,
    service: Annotated[ResolveService, Depends(get_resolve_service)],
) -> BulkResolveResponse:
    """Resolve multiple entity mentions in a single batch."""
    result = await service.handle_bulk_resolve(request)
    response.status_code = _bulk_status_code(result)
    return result
