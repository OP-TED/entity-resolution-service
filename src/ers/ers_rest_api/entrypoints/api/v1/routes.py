from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from ers.ers_rest_api.domain.data_transfer_objects import (
    EntityMentionRequest,
    ErrorResponse,
    LookupResponse,
    RefreshBulkRequest,
    RefreshBulkResponse,
    ResolveResponse,
)
from ers.ers_rest_api.entrypoints.api.dependencies import (
    get_lookup_service,
    get_refresh_bulk_service,
    get_resolve_service,
)
from ers.ers_rest_api.services.lookup_service import LookupService
from ers.ers_rest_api.services.refresh_bulk_service import RefreshBulkService
from ers.ers_rest_api.services.resolve_service import ResolveService
from ers.resolution_coordinator.domain.data_transfer_objects import ResolutionOutcome

router = APIRouter(tags=["Resolution"])


@router.post(
    "/resolve",
    response_model=ResolveResponse,
    responses={
        200: {"description": "Canonical resolution"},
        202: {"description": "Provisional resolution"},
    },
)
async def resolve(
    request: EntityMentionRequest,
    response: Response,
    service: Annotated[ResolveService, Depends(get_resolve_service)],
) -> ResolveResponse:
    """Resolve an entity mention and return canonical or provisional cluster ID."""
    result = await service.handle_resolve(request)
    if result.status == ResolutionOutcome.PROVISIONAL:
        response.status_code = status.HTTP_202_ACCEPTED
    return result


@router.get(
    "/lookup",
    response_model=LookupResponse,
    responses={
        404: {"model": ErrorResponse},
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
)
async def refresh_bulk(
    request: RefreshBulkRequest,
    service: Annotated[RefreshBulkService, Depends(get_refresh_bulk_service)],
) -> RefreshBulkResponse:
    """Retrieve delta of changed assignments since last synchronisation."""
    return await service.handle_refresh_bulk(request)
