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


@router.post(
    "/resolve-bulk",
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def resolve_bulk(
    request: BulkResolveRequest,
    service: Annotated[ResolveService, Depends(get_resolve_service)],
) -> BulkResolveResponse:
    """Resolve multiple entity mentions in a single batch."""
    return await service.handle_bulk_resolve(request)
