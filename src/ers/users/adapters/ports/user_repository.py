from abc import abstractmethod

from ers.commons.adapters.ports.repositories import (
    AsyncReadRepository,
    AsyncWriteRepository,
)
from ers.commons.services.dtos import PaginatedResult, PaginationParams
from ers.users.domain.user import User


class UserRepository(AsyncReadRepository[User, str], AsyncWriteRepository[User, str]):
    """Port for user persistence operations."""

    @abstractmethod
    async def find_by_email(self, email: str) -> User | None:
        """Find a user by email address. Returns None if not found."""

    @abstractmethod
    async def find_paginated(
        self,
        pagination: PaginationParams,
    ) -> PaginatedResult[User]:
        """Return paginated users ordered by latest first."""

    @abstractmethod
    async def delete(self, user_id: str) -> bool:
        """Delete a user by id. Returns True if deleted, False if not found."""
