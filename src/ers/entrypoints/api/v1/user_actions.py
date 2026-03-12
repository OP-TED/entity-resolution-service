from typing import Annotated

from fastapi import APIRouter, Depends

from ers.application.dtos import PaginatedResult, UserActionSummary
from ers.application.services import UserActionService
from ers.entrypoints.api.auth import AdminUser
from ers.entrypoints.api.dependencies import get_user_action_service
from ers.entrypoints.api.v1.schemas import Pagination

router = APIRouter(prefix="/user-actions", tags=["User Actions"])


@router.get("", response_model=PaginatedResult[UserActionSummary])
async def list_user_actions(
    pagination: Pagination,
    _admin: AdminUser,
    service: Annotated[UserActionService, Depends(get_user_action_service)],
) -> PaginatedResult[UserActionSummary]:
    """List paginated user actions ordered by latest first (admin only)."""
    return await service.list_user_actions(pagination)
