from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from ers.commons.domain.data_transfer_objects import PaginatedResult
from ers.curation.entrypoints.api.auth import AdminUser, CurrentUser, VerifiedUser
from ers.curation.entrypoints.api.dependencies import get_user_management_service
from ers.curation.entrypoints.api.v1.schemas import ErrorResponse, Pagination
from ers.users.domain.data_transfer_objects import (
    CreateUserRequest,
    UserContext,
    UserPatchRequest,
    UserResponse,
)
from ers.users.services import UserManagementService

router = APIRouter(prefix="/users", tags=["Users"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    response_description="The newly created user.",
)
async def create_user(
    body: CreateUserRequest,
    _admin: AdminUser,
    service: Annotated[UserManagementService, Depends(get_user_management_service)],
) -> UserResponse:
    """Create a new user (admin only)."""
    return await service.create_user(body)


@router.get(
    "",
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    response_description="Paginated list of users.",
)
async def list_users(
    pagination: Pagination,
    _user: VerifiedUser,
    service: Annotated[UserManagementService, Depends(get_user_management_service)],
    email: Annotated[str | None, Query(description="Partial email match")] = None,
) -> PaginatedResult[UserResponse]:
    """List all users (verified users)."""
    return await service.list_users(pagination, email_search=email)


@router.patch(
    "/{user_id}",
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    response_description="The updated user.",
)
async def patch_user(
    user_id: Annotated[str, Path(description="Unique identifier of the user to update.")],
    body: UserPatchRequest,
    _admin: AdminUser,
    service: Annotated[UserManagementService, Depends(get_user_management_service)],
) -> UserResponse:
    """Update user flags (admin only)."""
    return await service.patch_user(user_id, body)


@router.get(
    "/me",
    responses={401: {"model": ErrorResponse}},
    response_description="The currently authenticated user.",
)
async def get_current_user(
    user: CurrentUser,
) -> UserContext:
    """Get current authenticated user."""
    return user
