from abc import abstractmethod
from datetime import datetime

from erspec.models.core import EntityMentionIdentifier, UserAction

from ers.commons.adapters import MongoUserActionRepository, UserActionRepository
from ers.commons.domain.data_transfer_objects import PaginatedResult, PaginationParams


class UserActionCurationRepository(UserActionRepository):
    """Repository for persisting user action (curation) entries."""

    @abstractmethod
    async def find_paginated(
        self,
        pagination: PaginationParams,
    ) -> PaginatedResult[UserAction]:
        """Return paginated user actions ordered by latest first."""

    @abstractmethod
    async def has_current_action(
        self,
        about_entity_mention: EntityMentionIdentifier,
        since: datetime,
    ) -> bool:
        """Check if a UserAction exists for this entity mention since the given timestamp."""


class MongoUserActionCurationRepository(
    MongoUserActionRepository,
    UserActionCurationRepository,
):
    _model_class = UserAction
    _id_field = "id"

    async def find_paginated(
        self,
        pagination: PaginationParams,
    ) -> PaginatedResult[UserAction]:
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

    async def has_current_action(
        self,
        about_entity_mention: EntityMentionIdentifier,
        since: datetime,
    ) -> bool:
        count = await self._collection.count_documents(
            {
                "about_entity_mention": about_entity_mention.model_dump(mode="python"),
                "created_at": {"$gte": since},
            },
            limit=1,
        )
        return count > 0
