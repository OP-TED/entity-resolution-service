import uuid
from datetime import datetime, timezone

from ers.application.dtos import PaginatedResult, PaginationParams
from ers.application.auth_dtos import CreateUserRequest, UserPatchRequest, UserResponse
from ers.application.exceptions import ApplicationError, NotFoundError
from ers.application.ports.password_hasher import PasswordHasher
from ers.application.ports.user_repository import UserRepository
from ers.domain.user import User


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        is_verified=user.is_verified,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


class UserManagementService:
    """Admin-only user management operations."""

    def __init__(
        self,
        user_repository: UserRepository,
        password_hasher: PasswordHasher,
    ) -> None:
        self._user_repo = user_repository
        self._hasher = password_hasher

    async def create_user(self, dto: CreateUserRequest) -> UserResponse:
        """Create a new user (admin operation)."""
        existing = await self._user_repo.find_by_email(dto.email)
        if existing is not None:
            raise ApplicationError("A user with this email already exists")

        user = User(
            id=str(uuid.uuid4()),
            email=dto.email,
            hashed_password=self._hasher.hash(dto.password),
            is_active=dto.is_active,
            is_superuser=dto.is_superuser,
            is_verified=dto.is_verified,
            created_at=datetime.now(timezone.utc),
        )
        await self._user_repo.save(user)
        return _to_user_response(user)

    async def list_users(
        self,
        pagination: PaginationParams,
    ) -> PaginatedResult[UserResponse]:
        """Return paginated users."""
        users = await self._user_repo.find_paginated(pagination)
        return PaginatedResult(
            count=users.count,
            previous=users.previous,
            next=users.next,
            results=[_to_user_response(user) for user in users.results],
        )

    async def patch_user(self, user_id: str, dto: UserPatchRequest) -> UserResponse:
        """Update user flags (admin operation)."""
        user = await self._user_repo.find_by_id(user_id)
        if user is None:
            raise NotFoundError("User", user_id)

        updates = dto.model_dump(exclude_none=True)
        if updates:
            updates["updated_at"] = datetime.now(timezone.utc)
            user = user.model_copy(update=updates)
            await self._user_repo.save(user)

        return _to_user_response(user)

    async def delete_user(self, user_id: str) -> None:
        """Delete a user by id (admin operation)."""
        deleted = await self._user_repo.delete(user_id)
        if not deleted:
            raise NotFoundError("User", user_id)
