from abc import abstractmethod

from ers.commons.adapters.repository import (
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
    async def find_by_ids(self, user_ids: list[str]) -> list[User]:
        """Return users matching the given IDs."""

    @abstractmethod
    async def find_paginated(
        self,
        pagination: PaginationParams,
        email_search: str | None = None,
    ) -> PaginatedResult[User]:
        """Return paginated users ordered by latest first."""

    @abstractmethod
    async def count_active_admins(self) -> int:
        """Return the number of active superuser accounts."""


class MongoUserRepository(BaseMongoRepository[User, str], UserRepository):
    """MongoDB-backed user repository."""

    _model_class = User
    _id_field = "id"
    _collection_name = "users"

    async def find_by_email(self, email: str) -> User | None:
        doc = await self._collection.find_one({"email": email})
        if doc is None:
            return None
        return self._from_document(doc)

    async def find_by_ids(self, user_ids: list[str]) -> list[User]:
        if not user_ids:
            return []
        cursor = self._collection.find({"_id": {"$in": user_ids}})
        return [self._from_document(doc) async for doc in cursor]

    async def find_paginated(
        self,
        pagination: PaginationParams,
        email_search: str | None = None,
    ) -> PaginatedResult[User]:
        query: dict = {}
        if email_search is not None:
            query["email"] = {"$regex": email_search, "$options": "i"}
        skip = (pagination.page - 1) * pagination.per_page
        count = await self._collection.count_documents(query)
        cursor = (
            self._collection.find(query)
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

    async def count_active_admins(self) -> int:
        return await self._collection.count_documents(
            {"is_active": True, "is_superuser": True},
        )
