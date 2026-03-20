import uuid
from datetime import UTC, datetime

from ers.commons.domain.data_transfer_objects import PaginatedResult, PaginationParams
from ers.commons.services.exceptions import ApplicationError, NotFoundError
from ers.users.adapters.hasher import PasswordHasher
from ers.users.adapters.user_repository import UserRepository
from ers.users.domain.data_transfer_objects import (
    CreateUserRequest,
    UserPatchRequest,
    UserResponse,
)
from ers.users.domain.exceptions import LastAdminError
from ers.users.domain.users import User


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
            created_at=datetime.now(UTC),
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
        """Update user flags (admin operation).

        Raises:
             LastAdminError when deactivating the last active administrator.
        """
        user = await self._user_repo.find_by_id(user_id)
        if user is None:
            raise NotFoundError("User", user_id)

        updates = dto.model_dump(exclude_none=True)
        if updates:
            await self._guard_last_admin(user, updates)
            updates["updated_at"] = datetime.now(UTC)
            user = user.model_copy(update=updates)
            await self._user_repo.save(user)

        return _to_user_response(user)

    async def _guard_last_admin(self, user: User, updates: dict) -> None:
        """Raise LastAdminError if deactivating the last active admin."""
        is_deactivating = updates.get("is_active") is False and user.is_active
        is_removing_superuser = updates.get("is_superuser") is False and user.is_superuser
        if (is_deactivating and user.is_superuser) or (is_removing_superuser and user.is_active):
            active_admin_count = await self._user_repo.count_active_admins()
            if active_admin_count <= 1:
                raise LastAdminError()
