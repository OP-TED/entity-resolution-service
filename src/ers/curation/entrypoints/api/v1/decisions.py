from typing import Annotated, cast

from fastapi import APIRouter, Depends, Path, Query, Response, status

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
from ers.curation.services import decision_curation_service as decision_svc

router = APIRouter(prefix="/curation/decisions", tags=["Decisions"])


@router.get(
    "",
    responses={
        400: {"model": ErrorResponse},
        503: {
            "model": ErrorResponse,
            "description": "MongoDB unavailable",
        },
    },
    response_description="Cursor-paginated list of curation decisions.",
)
async def list_decisions(
    filters: DecisionFiltersDep,
    cursor_params: CursorPagination,
    user: VerifiedUser,
    service: Annotated[DecisionCurationService, Depends(get_decision_curation_service)],
    ever_reviewed: Annotated[
        bool | None,
        Query(
            description=(
                "Filter on whether any curator action has ever been recorded against "
                "the decision (previous_review_count > 0). Omit to disable."
            )
        ),
    ] = None,
    reviewed_since_placement: Annotated[
        bool | None,
        Query(
            description=(
                "Filter on whether a curator action exists since the current placement "
                "(created_at after updated_at, else created_at). Omit to disable. "
                "Combine ever_reviewed=true with reviewed_since_placement=false to list "
                "decisions that need re-visiting after an ERE update."
            )
        ),
    ] = None,
    reviewed: Annotated[
        bool | None,
        Query(
            deprecated=True,
            description=(
                "Deprecated alias of reviewed_since_placement. Ignored when "
                "reviewed_since_placement is provided."
            ),
        ),
    ] = None,
) -> CursorPage[DecisionSummary]:
    """Retrieve cursor-paginated list of decisions with optional filtering.

    The UI composes the four review states from the two row primitives
    (``previous_review_count`` and ``reviewed_since_placement``) and filters via
    the two orthogonal query parameters.

    Args:
        filters: Field-level filter criteria (entity type, confidence, etc.).
        cursor_params: Cursor-based pagination parameters.
        user: Authenticated and verified curator.
        service: Decision curation service (injected).
        ever_reviewed: Filter on lifetime review existence.
        reviewed_since_placement: Filter on review since the current placement.
        reviewed: Deprecated alias of ``reviewed_since_placement``.
    """
    return await service.list_decisions(
        filters=filters,
        cursor_params=cursor_params,
        ever_reviewed=ever_reviewed,
        reviewed_since_placement=reviewed_since_placement,
        reviewed=reviewed,
    )


@router.get(
    "/{decision_id}/proposed-canonical-entity",
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse, "description": "MongoDB unavailable"},
    },
    response_description="The proposed canonical entity cluster for the given decision.",
)
async def get_proposed_canonical_entity(
    decision_id: Annotated[str, Path(description="Unique identifier of the curation decision.")],
    user: VerifiedUser,
    service: Annotated[CanonicalEntityService, Depends(get_canonical_entity_service)],
) -> CanonicalEntityPreview:
    """Get the proposed canonical entity for a given decision."""
    return await service.get_proposed_canonical_entity(decision_id)


@router.get(
    "/{decision_id}/alternative-canonical-entities",
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse, "description": "MongoDB unavailable"},
    },
    response_description="Paginated list of alternative canonical entity clusters for the given decision.",
)
async def get_alternative_canonical_entities(
    decision_id: Annotated[str, Path(description="Unique identifier of the curation decision.")],
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
    response_description="Decision accepted; no content returned.",
)
async def accept_decision(
    decision_id: Annotated[str, Path(description="Unique identifier of the curation decision.")],
    user: VerifiedUser,
    service: Annotated[DecisionCurationService, Depends(get_decision_curation_service)],
) -> Response:
    """Accept the proposed canonical entity match."""
    await service.accept_decision(decision_id, actor=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{decision_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    response_description="Decision rejected; no content returned.",
)
async def reject_decision(
    decision_id: Annotated[str, Path(description="Unique identifier of the curation decision.")],
    user: VerifiedUser,
    service: Annotated[DecisionCurationService, Depends(get_decision_curation_service)],
) -> Response:
    """Reject the proposed canonical entity match."""
    await service.reject_decision(decision_id, actor=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{decision_id}/assign",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    response_description="Decision assigned to the specified cluster; no content returned.",
)
async def assign_decision(
    decision_id: Annotated[str, Path(description="Unique identifier of the curation decision.")],
    body: AssignRequest,
    user: VerifiedUser,
    service: Annotated[DecisionCurationService, Depends(get_decision_curation_service)],
) -> Response:
    """Assign the subject entity mention to a specific cluster."""
    await service.assign_decision(
        decision_id,
        cluster_id=body.cluster_id,
        actor=user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/bulk-accept",
    responses={400: {"model": ErrorResponse}},
    response_description="Per-decision results for the bulk accept operation.",
)
async def bulk_accept_decisions(
    body: BulkActionRequest,
    user: VerifiedUser,
    service: Annotated[DecisionCurationService, Depends(get_decision_curation_service)],
) -> BulkActionResponse:
    """Accept multiple decisions in a single request."""
    return cast(
        BulkActionResponse,
        await decision_svc.bulk_accept_decisions(body.decision_ids, actor=user.id, service=service),
    )


@router.post(
    "/bulk-reject",
    responses={400: {"model": ErrorResponse}},
    response_description="Per-decision results for the bulk reject operation.",
)
async def bulk_reject_decisions(
    body: BulkActionRequest,
    user: VerifiedUser,
    service: Annotated[DecisionCurationService, Depends(get_decision_curation_service)],
) -> BulkActionResponse:
    """Reject multiple decisions in a single request."""
    return cast(
        BulkActionResponse,
        await decision_svc.bulk_reject_decisions(body.decision_ids, actor=user.id, service=service),
    )
