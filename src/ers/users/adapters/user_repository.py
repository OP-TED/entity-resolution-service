from abc import abstractmethod

from ers.commons.adapters import (
    AsyncReadRepository,
    AsyncWriteRepository,
    BaseMongoRepository,
)
from ers.commons.domain.data_transfer_objects import PaginatedResult, PaginationParams
from ers.users.domain.users import User


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


class MongoUserRepository(BaseMongoRepository[User, str], UserRepository):
    """MongoDB-backed user repository."""

    _model_class = User
    _id_field = "id"

    async def find_by_email(self, email: str) -> User | None:
        doc = await self._collection.find_one({"email": email})
        if doc is None:
            return None
        return self._from_document(doc)

    async def find_paginated(
        self,
        pagination: PaginationParams,
    ) -> PaginatedResult[User]:
        skip = (pagination.page - 1) * pagination.per_page
        count = await self._collection.count_documents({})
        cursor = (
            self._collection.find({})
            .sort([("created_at", -1)])
            .skip(skip)
            .limit(pagination.per_page)
        )
        results = [self._from_document(doc) async for doc in cursor]

        total_pages = (count + pagination.per_page - 1) // pagination.per_page if count > 0 else 0

        return PaginatedResult(
            count=count,
            previous=pagination.page - 1 if pagination.page > 1 else None,
            next=pagination.page + 1 if pagination.page < total_pages else None,
            results=results,
        )

    async def delete(self, user_id: str) -> bool:
        result = await self._collection.delete_one({"_id": user_id})
        return result.deleted_count > 0
