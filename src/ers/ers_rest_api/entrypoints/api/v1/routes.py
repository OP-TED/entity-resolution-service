from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.ers_rest_api.domain.errors import ErrorResponse
from ers.ers_rest_api.domain.lookup import (
    LookupResponse,
    RefreshBulkRequest,
    RefreshBulkResponse,
)
from ers.ers_rest_api.domain.resolution import (
    EntityMentionResolutionRequest,
    EntityMentionResolutionResult,
)
from ers.ers_rest_api.entrypoints.api.dependencies import (
    get_lookup_service,
    get_refresh_bulk_service,
    get_resolve_service,
)
from ers.ers_rest_api.services.lookup_service import LookupService
from ers.ers_rest_api.services.refresh_bulk_service import RefreshBulkService
from ers.ers_rest_api.services.resolve_service import ResolveService

router = APIRouter(tags=["Resolution"])


@router.post(
    "/resolve",
    response_model=EntityMentionResolutionResult,
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


@router.get(
    "/lookup",
    response_model=LookupResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        404: {"model": ErrorResponse, "description": "Mention not found"},
    },
)
async def lookup(
    source_id: Annotated[str, Query(min_length=1, description="Source system identifier")],
    request_id: Annotated[str, Query(min_length=1, description="Request identifier")],
    entity_type: Annotated[str, Query(min_length=1, description="Entity type")],
    service: Annotated[LookupService, Depends(get_lookup_service)],
) -> LookupResponse:
    """Retrieve current cluster assignment for a mention triad."""
    return await service.handle_lookup(source_id, request_id, entity_type)


@router.post(
    "/refresh-bulk",
    response_model=RefreshBulkResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def refresh_bulk(
    request: RefreshBulkRequest,
    service: Annotated[RefreshBulkService, Depends(get_refresh_bulk_service)],
) -> RefreshBulkResponse:
    """Retrieve delta of changed assignments since last synchronisation."""
    return await service.handle_refresh_bulk(request)
