from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ers.ers_rest_api.domain.errors import ErrorResponse
from ers.ers_rest_api.domain.lookup import (
    BulkLookupRequest,
    BulkLookupResponse,
    LookupResponse,
    RefreshBulkRequest,
    RefreshBulkResponse,
)
from ers.ers_rest_api.entrypoints.api.dependencies import (
    get_lookup_service,
    get_refresh_bulk_service,
)
from ers.ers_rest_api.services.lookup_service import LookupService
from ers.ers_rest_api.services.refresh_bulk_service import RefreshBulkService

router = APIRouter(tags=["Lookup"])


@router.get(
    "/lookup",
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
    "/lookup-bulk",
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def lookup_bulk(
    request: BulkLookupRequest,
    service: Annotated[LookupService, Depends(get_lookup_service)],
) -> BulkLookupResponse:
    """Look up cluster assignments for multiple entity mentions in a single batch."""
    return await service.handle_bulk_lookup(request)


@router.post(
    "/refresh-bulk",
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
