from datetime import datetime
from typing import Annotated

from erspec.models.core import UserActionType
from fastapi import APIRouter, Depends, Query

from ers.commons.domain.data_transfer_objects import PaginatedResult
from ers.curation.domain.data_transfer_objects import UserActionFilters, UserActionSummary
from ers.curation.entrypoints.api.auth import AdminUser
from ers.curation.entrypoints.api.dependencies import get_user_action_service
from ers.curation.entrypoints.api.v1.schemas import ErrorResponse, Pagination
from ers.curation.services import UserActionService

router = APIRouter(prefix="/user-actions", tags=["User Actions"])


@router.get(
    "",
    response_model=PaginatedResult[UserActionSummary],
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
async def list_user_actions(
    pagination: Pagination,
    _admin: AdminUser,
    service: Annotated[UserActionService, Depends(get_user_action_service)],
    action_type: Annotated[UserActionType | None, Query()] = None,
    actor: Annotated[str | None, Query()] = None,
    time_range_start: Annotated[datetime | None, Query()] = None,
    time_range_end: Annotated[datetime | None, Query()] = None,
) -> PaginatedResult[UserActionSummary]:
    """List paginated user actions ordered by latest first (admin only)."""
    filters = None
    if any(v is not None for v in (action_type, actor, time_range_start, time_range_end)):
        filters = UserActionFilters(
            action_type=action_type,
            actor=actor,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )
    return await service.list_user_actions(pagination, filters)
