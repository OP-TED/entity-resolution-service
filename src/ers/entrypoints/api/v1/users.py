from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from ers.application.auth_dtos import (
    CreateUserRequest,
    UserContext,
    UserPatchRequest,
    UserResponse,
)
from ers.application.dtos import PaginatedResult
from ers.application.services import UserManagementService
from ers.entrypoints.api.auth import AdminUser, CurrentUser
from ers.entrypoints.api.dependencies import get_user_management_service
from ers.entrypoints.api.v1.schemas import Pagination

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    _admin: AdminUser,
    service: Annotated[UserManagementService, Depends(get_user_management_service)],
) -> UserResponse:
    """Create a new user (admin only)."""
    return await service.create_user(body)


@router.get("", response_model=PaginatedResult[UserResponse])
async def list_users(
    pagination: Pagination,
    _admin: AdminUser,
    service: Annotated[UserManagementService, Depends(get_user_management_service)],
) -> PaginatedResult[UserResponse]:
    """List all users (admin only)."""
    return await service.list_users(pagination)


@router.patch("/{user_id}", response_model=UserResponse)
async def patch_user(
    user_id: str,
    body: UserPatchRequest,
    _admin: AdminUser,
    service: Annotated[UserManagementService, Depends(get_user_management_service)],
) -> UserResponse:
    """Update user flags (admin only)."""
    return await service.patch_user(user_id, body)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    _admin: AdminUser,
    service: Annotated[UserManagementService, Depends(get_user_management_service)],
) -> Response:
    """Delete a user (admin only)."""
    await service.delete_user(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserContext)
async def get_current_user(
    user: CurrentUser,
) -> UserContext:
    """Get current authenticated user."""
    return user
