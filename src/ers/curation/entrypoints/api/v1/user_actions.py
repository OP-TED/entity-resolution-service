from datetime import datetime
from typing import Annotated

from erspec.models.core import UserActionType
from fastapi import APIRouter, Depends, Query

from ers.commons.domain.data_transfer_objects import CursorPage, PaginatedResult
from ers.curation.domain.data_transfer_objects import (
    BaseOrdering,
    CanonicalEntityPreview,
    UserActionFilters,
    UserActionSummary,
)
from ers.curation.entrypoints.api.auth import VerifiedUser
from ers.curation.entrypoints.api.dependencies import (
    get_canonical_entity_service,
    get_user_action_service,
)
from ers.curation.entrypoints.api.v1.schemas import CursorPagination, ErrorResponse, Pagination
from ers.curation.services import CanonicalEntityService, UserActionService

router = APIRouter(prefix="/user-actions", tags=["User Actions"])


@router.get(
    "",
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
async def list_user_actions(
    cursor_params: CursorPagination,
    _user: VerifiedUser,
    service: Annotated[UserActionService, Depends(get_user_action_service)],
    action_type: Annotated[UserActionType | None, Query()] = None,
    actor: Annotated[str | None, Query()] = None,
    time_range_start: Annotated[datetime | None, Query()] = None,
    time_range_end: Annotated[datetime | None, Query()] = None,
    ordering: Annotated[BaseOrdering | None, Query()] = None,
) -> CursorPage[UserActionSummary]:
    """List cursor-paginated user actions with optional filtering."""
    filters = None
    if any(v is not None for v in (action_type, actor, time_range_start, time_range_end, ordering)):
        filters = UserActionFilters(
            action_type=action_type,
            actor=actor,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            ordering=ordering,
        )
    return await service.list_user_actions(cursor_params, filters)


@router.get(
    "/{action_id}/selected-cluster",
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def get_selected_cluster(
    action_id: str,
    _user: VerifiedUser,
    service: Annotated[UserActionService, Depends(get_user_action_service)],
    canonical_service: Annotated[CanonicalEntityService, Depends(get_canonical_entity_service)],
) -> CanonicalEntityPreview | None:
    """Get the selected cluster preview with top entity mentions."""
    return await service.get_selected_cluster_preview(action_id, canonical_service)


@router.get(
    "/{action_id}/candidates",
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def get_candidates(
    action_id: str,
    pagination: Pagination,
    _user: VerifiedUser,
    service: Annotated[UserActionService, Depends(get_user_action_service)],
    canonical_service: Annotated[CanonicalEntityService, Depends(get_canonical_entity_service)],
) -> PaginatedResult[CanonicalEntityPreview]:
    """Get paginated candidate cluster previews with top entity mentions."""
    return await service.get_candidate_previews(action_id, pagination, canonical_service)
