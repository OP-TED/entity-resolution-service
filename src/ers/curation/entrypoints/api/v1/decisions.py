from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from ers.commons.domain.data_transfer_objects import CursorPage, PaginatedResult
from ers.curation.domain.data_transfer_objects import (
    AssignRequest,
    BulkActionRequest,
    BulkActionResponse,
    CanonicalEntityPreview,
    DecisionSummary,
)
from ers.curation.entrypoints.api.auth import VerifiedUser
from ers.curation.entrypoints.api.dependencies import (
    get_canonical_entity_service,
    get_decision_curation_service,
)
from ers.curation.entrypoints.api.v1.schemas import (
    CursorPagination,
    DecisionFiltersDep,
    ErrorResponse,
    Pagination,
)
from ers.curation.services import (
    CanonicalEntityService,
    DecisionCurationService,
)

router = APIRouter(prefix="/curation/decisions", tags=["Decisions"])


@router.get(
    "",
    response_model=CursorPage[DecisionSummary],
    responses={400: {"model": ErrorResponse}},
)
async def list_decisions(
    filters: DecisionFiltersDep,
    cursor_params: CursorPagination,
    user: VerifiedUser,
    service: Annotated[DecisionCurationService, Depends(get_decision_curation_service)],
) -> CursorPage[DecisionSummary]:
    """Retrieve cursor-paginated list of decisions with optional filtering."""
    return await service.list_decisions(filters=filters, cursor_params=cursor_params)


@router.get(
    "/{decision_id}/proposed-canonical-entity",
    response_model=CanonicalEntityPreview,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_proposed_canonical_entity(
    decision_id: str,
    user: VerifiedUser,
    service: Annotated[CanonicalEntityService, Depends(get_canonical_entity_service)],
) -> CanonicalEntityPreview:
    """Get the proposed canonical entity for a given decision."""
    return await service.get_proposed_canonical_entity(decision_id)


@router.get(
    "/{decision_id}/alternative-canonical-entities",
    response_model=PaginatedResult[CanonicalEntityPreview],
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_alternative_canonical_entities(
    decision_id: str,
    pagination: Pagination,
    user: VerifiedUser,
    service: Annotated[CanonicalEntityService, Depends(get_canonical_entity_service)],
) -> PaginatedResult[CanonicalEntityPreview]:
    """Get alternative canonical entities for a given decision."""
    return await service.get_alternative_canonical_entities(decision_id, pagination)


@router.post(
    "/{decision_id}/accept",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def accept_decision(
    decision_id: str,
    user: VerifiedUser,
    service: Annotated[DecisionCurationService, Depends(get_decision_curation_service)],
) -> Response:
    """Accept the proposed canonical entity match."""
    await service.accept_decision(decision_id, actor=user.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{decision_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def reject_decision(
    decision_id: str,
    user: VerifiedUser,
    service: Annotated[DecisionCurationService, Depends(get_decision_curation_service)],
) -> Response:
    """Reject the proposed canonical entity match."""
    await service.reject_decision(decision_id, actor=user.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{decision_id}/assign",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def assign_decision(
    decision_id: str,
    body: AssignRequest,
    user: VerifiedUser,
    service: Annotated[DecisionCurationService, Depends(get_decision_curation_service)],
) -> Response:
    """Assign the subject entity mention to a specific cluster."""
    await service.assign_decision(
        decision_id,
        cluster_id=body.cluster_id,
        actor=user.email,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/bulk-accept",
    response_model=BulkActionResponse,
    responses={400: {"model": ErrorResponse}},
)
async def bulk_accept_decisions(
    body: BulkActionRequest,
    user: VerifiedUser,
    service: Annotated[DecisionCurationService, Depends(get_decision_curation_service)],
) -> BulkActionResponse:
    """Accept multiple decisions in a single request."""
    return await service.bulk_accept_decisions(body.decision_ids, actor=user.email)


@router.post(
    "/bulk-reject",
    response_model=BulkActionResponse,
    responses={400: {"model": ErrorResponse}},
)
async def bulk_reject_decisions(
    body: BulkActionRequest,
    user: VerifiedUser,
    service: Annotated[DecisionCurationService, Depends(get_decision_curation_service)],
) -> BulkActionResponse:
    """Reject multiple decisions in a single request."""
    return await service.bulk_reject_decisions(body.decision_ids, actor=user.email)
