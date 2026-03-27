from abc import abstractmethod
from datetime import datetime

from erspec.models.core import EntityMentionIdentifier, UserAction

from ers.commons.adapters.user_action_repository import (
    MongoUserActionRepository,
    UserActionRepository,
)
from ers.commons.domain.data_transfer_objects import PaginatedResult, PaginationParams
from ers.curation.domain.data_transfer_objects import UserActionFilters


class UserActionCurationRepository(UserActionRepository):
    """Repository for persisting user action (curation) entries."""

    @abstractmethod
    async def find_paginated(
        self,
        pagination: PaginationParams,
        filters: UserActionFilters | None = None,
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
        filters: UserActionFilters | None = None,
    ) -> PaginatedResult[UserAction]:
        query = self._build_filter_query(filters)
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

    @staticmethod
    def _build_filter_query(filters: UserActionFilters | None) -> dict:
        if filters is None:
            return {}
        query: dict = {}
        if filters.action_type is not None:
            query["action_type"] = filters.action_type.value
        if filters.actor is not None:
            query["actor"] = filters.actor
        time_constraint: dict = {}
        if filters.time_range_start is not None:
            time_constraint["$gte"] = filters.time_range_start
        if filters.time_range_end is not None:
            time_constraint["$lte"] = filters.time_range_end
        if time_constraint:
            query["created_at"] = time_constraint
        return query
