from abc import abstractmethod
from datetime import datetime
from typing import Any

from erspec.models.core import EntityMentionIdentifier, UserAction

from ers.commons.adapters.user_action_repository import (
    MongoUserActionRepository,
    UserActionRepository,
)
from ers.commons.domain.cursor import decode_cursor, encode_cursor
from ers.commons.domain.data_transfer_objects import CursorPage, CursorParams
from ers.curation.domain.data_transfer_objects import BaseOrdering, UserActionFilters


class UserActionCurationRepository(UserActionRepository):
    """Repository for persisting user action (curation) entries."""

    @abstractmethod
    async def find_with_cursor(
        self,
        cursor_params: CursorParams,
        filters: UserActionFilters | None = None,
    ) -> CursorPage[UserAction]:
        """Return cursor-paginated user actions with optional filtering."""

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

    _SORT_FIELD_MAP: dict[BaseOrdering, tuple[str, bool]] = {
        BaseOrdering.CREATED_AT_ASC: ("created_at", True),
        BaseOrdering.CREATED_AT_DESC: ("created_at", False),
    }

    def _get_sort_info(self, filters: UserActionFilters | None) -> tuple[str, bool]:
        ordering = filters.ordering if filters is not None else None
        if ordering is None:
            return "created_at", False
        return self._SORT_FIELD_MAP[ordering]

    def _build_cursor_condition(
        self,
        sort_value: Any,
        last_id: str,
        ascending: bool,
    ) -> dict[str, Any]:
        id_op = "$gt" if ascending else "$lt"
        val_op = "$gt" if ascending else "$lt"
        if sort_value is None:
            return {"created_at": None, "_id": {id_op: last_id}}
        return {
            "$or": [
                {"created_at": {val_op: sort_value}},
                {"created_at": sort_value, "_id": {id_op: last_id}},
            ]
        }

    async def find_with_cursor(
        self,
        cursor_params: CursorParams,
        filters: UserActionFilters | None = None,
    ) -> CursorPage[UserAction]:
        query = self._build_filter_query(filters)
        sort_field, ascending = self._get_sort_info(filters)
        direction = 1 if ascending else -1
        sort = [(sort_field, direction), ("_id", direction)]

        if cursor_params.cursor is not None:
            raw_value, last_id = decode_cursor(cursor_params.cursor)
            sort_value = datetime.fromisoformat(raw_value) if raw_value is not None else None
            cursor_condition = self._build_cursor_condition(sort_value, last_id, ascending)
            query = {"$and": [query, cursor_condition]}

        fetch_limit = cursor_params.limit + 1
        cursor = self._collection.find(query).sort(sort).limit(fetch_limit)
        results = [self._from_document(doc) async for doc in cursor]

        next_cursor = None
        if len(results) > cursor_params.limit:
            results = results[: cursor_params.limit]
            last = results[-1]
            next_cursor = encode_cursor(last.created_at, last.id)

        return CursorPage(results=results, next_cursor=next_cursor)

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
