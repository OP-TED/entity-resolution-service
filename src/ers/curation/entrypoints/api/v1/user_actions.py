from typing import Annotated

from fastapi import APIRouter, Depends

from ers.commons.domain.dtos import PaginatedResult
from ers.curation.domain.dtos import UserActionSummary
from ers.curation.entrypoints.api.auth import AdminUser
from ers.curation.entrypoints.api.dependencies import get_user_action_service
from ers.curation.entrypoints.api.v1.schemas import Pagination
from ers.curation.services import UserActionService

router = APIRouter(prefix="/user-actions", tags=["User Actions"])


@router.get("", response_model=PaginatedResult[UserActionSummary])
async def list_user_actions(
    pagination: Pagination,
    _admin: AdminUser,
    service: Annotated[UserActionService, Depends(get_user_action_service)],
) -> PaginatedResult[UserActionSummary]:
    """List paginated user actions ordered by latest first (admin only)."""
    return await service.list_user_actions(pagination)
