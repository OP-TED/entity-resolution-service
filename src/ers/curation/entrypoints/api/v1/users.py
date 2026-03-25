from typing import Annotated

from fastapi import APIRouter, Depends, status

from ers.commons.domain.data_transfer_objects import PaginatedResult
from ers.curation.entrypoints.api.auth import AdminUser, CurrentUser
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
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
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
    response_model=PaginatedResult[UserResponse],
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
async def list_users(
    pagination: Pagination,
    _admin: AdminUser,
    service: Annotated[UserManagementService, Depends(get_user_management_service)],
) -> PaginatedResult[UserResponse]:
    """List all users (admin only)."""
    return await service.list_users(pagination)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def patch_user(
    user_id: str,
    body: UserPatchRequest,
    _admin: AdminUser,
    service: Annotated[UserManagementService, Depends(get_user_management_service)],
) -> UserResponse:
    """Update user flags (admin only)."""
    return await service.patch_user(user_id, body)


@router.get(
    "/me",
    response_model=UserContext,
    responses={401: {"model": ErrorResponse}},
)
async def get_current_user(
    user: CurrentUser,
) -> UserContext:
    """Get current authenticated user."""
    return user
