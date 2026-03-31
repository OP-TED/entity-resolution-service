from abc import abstractmethod
from datetime import datetime
from typing import Any

from erspec.models.core import Decision, EntityMentionIdentifier

from ers.commons.adapters.decision_repository import (
    DecisionRepository,
    MongoDecisionRepository,
)
from ers.commons.domain.cursor import decode_cursor, encode_cursor
from ers.commons.domain.data_transfer_objects import CursorPage, CursorParams
from ers.curation.domain.data_transfer_objects import (
    DecisionFilters,
    DecisionOrdering,
)


class DecisionCurationRepository(DecisionRepository):
    """Repository for decision projection persistence and curation specific querying."""

    @abstractmethod
    async def find_with_filters(
        self,
        filters: DecisionFilters,
        cursor_params: CursorParams,
        mention_identifiers: list[EntityMentionIdentifier] | None = None,
    ) -> CursorPage[Decision]:
        """Find decisions matching filters with cursor-based pagination.

        Args:
            filters: Filter criteria for decision retrieval.
            cursor_params: Cursor-based pagination parameters (cursor, limit).
            mention_identifiers: When provided, restricts results to decisions
                whose ``about_entity_mention`` is in this list (used for
                full-text search pre-filtering).
        """

    @abstractmethod
    async def find_mention_ids_by_cluster(
        self,
        cluster_id: str,
        limit: int,
    ) -> list[EntityMentionIdentifier]:
        """Return entity mention identifiers for decisions placed in a cluster."""

    @abstractmethod
    async def count_distinct_clusters(self) -> int:
        """Return the number of distinct cluster IDs across all decisions."""

    @abstractmethod
    async def average_cluster_size(self) -> float:
        """Return the average number of decisions per cluster."""


class MongoDecisionCurationRepository(
    MongoDecisionRepository,
    DecisionCurationRepository,
):
    """MongoDB repository for decision projections with curation-specific queries."""

    _SORT_FIELD_MAP: dict[DecisionOrdering, tuple[str, bool]] = {
        DecisionOrdering.CONFIDENCE_ASC: ("current_placement.confidence_score", True),
        DecisionOrdering.CONFIDENCE_DESC: ("current_placement.confidence_score", False),
        DecisionOrdering.CREATED_AT_ASC: ("created_at", True),
        DecisionOrdering.CREATED_AT_DESC: ("created_at", False),
        DecisionOrdering.UPDATED_AT_ASC: ("updated_at", True),
        DecisionOrdering.UPDATED_AT_DESC: ("updated_at", False),
    }

    _DATETIME_SORT_FIELDS: set[str] = {"created_at", "updated_at"}

    def _build_query(self, filters: DecisionFilters) -> dict[str, Any]:
        query: dict[str, Any] = {}

        if filters.entity_type is not None:
            query["about_entity_mention.entity_type"] = filters.entity_type

        placement_range: dict[str, dict[str, float]] = {}
        if filters.confidence_min is not None:
            placement_range.setdefault("current_placement.confidence_score", {})["$gte"] = (
                filters.confidence_min
            )
        if filters.confidence_max is not None:
            placement_range.setdefault("current_placement.confidence_score", {})["$lte"] = (
                filters.confidence_max
            )
        if filters.similarity_min is not None:
            placement_range.setdefault("current_placement.similarity_score", {})["$gte"] = (
                filters.similarity_min
            )
        if filters.similarity_max is not None:
            placement_range.setdefault("current_placement.similarity_score", {})["$lte"] = (
                filters.similarity_max
            )
        query.update(placement_range)

        return query

    def _get_sort_info(self, ordering: DecisionOrdering | None) -> tuple[str, bool]:
        """Return (mongo_field_name, is_ascending) for the given ordering."""
        if ordering is None:
            return "created_at", False
        return self._SORT_FIELD_MAP[ordering]

    def _build_sort(self, ordering: DecisionOrdering | None) -> list[tuple[str, int]]:
        field, ascending = self._get_sort_info(ordering)
        direction = 1 if ascending else -1
        return [(field, direction), ("_id", direction)]

    def _build_cursor_condition(
        self,
        sort_field: str,
        sort_value: Any,
        last_id: str,
        ascending: bool,
    ) -> dict[str, Any]:
        """Build MongoDB filter for cursor-based seek."""
        id_op = "$gt" if ascending else "$lt"
        val_op = "$gt" if ascending else "$lt"

        if sort_value is None:
            if ascending:
                return {
                    "$or": [
                        {sort_field: None, "_id": {id_op: last_id}},
                        {sort_field: {"$ne": None}},
                    ]
                }
            return {sort_field: None, "_id": {id_op: last_id}}

        return {
            "$or": [
                {sort_field: {val_op: sort_value}},
                {sort_field: sort_value, "_id": {id_op: last_id}},
            ]
        }

    def _extract_sort_value(self, decision: Decision, sort_field: str) -> float | datetime | None:
        if sort_field == "current_placement.confidence_score":
            return decision.current_placement.confidence_score
        if sort_field == "created_at":
            return decision.created_at
        if sort_field == "updated_at":
            return decision.updated_at
        return None

    def _parse_cursor_sort_value(self, value: Any, sort_field: str) -> Any:
        if value is None:
            return None
        if sort_field in self._DATETIME_SORT_FIELDS:
            return datetime.fromisoformat(value)
        return value

    async def find_with_filters(
        self,
        filters: DecisionFilters,
        cursor_params: CursorParams,
        mention_identifiers: list[EntityMentionIdentifier] | None = None,
    ) -> CursorPage[Decision]:
        query = self._build_query(filters)

        if mention_identifiers is not None:
            id_docs = [
                {
                    "source_id": mi.source_id,
                    "request_id": mi.request_id,
                    "entity_type": mi.entity_type,
                }
                for mi in mention_identifiers
            ]
            query["about_entity_mention"] = {"$in": id_docs}

        count = await self._collection.count_documents(query)

        sort_field, ascending = self._get_sort_info(filters.ordering)
        sort = self._build_sort(filters.ordering)

        if cursor_params.cursor is not None:
            raw_value, last_id = decode_cursor(cursor_params.cursor)
            sort_value = self._parse_cursor_sort_value(raw_value, sort_field)
            cursor_condition = self._build_cursor_condition(
                sort_field, sort_value, last_id, ascending
            )
            query = {"$and": [query, cursor_condition]}

        fetch_limit = cursor_params.limit + 1
        cursor = self._collection.find(query).sort(sort).limit(fetch_limit)
        results = [self._from_document(doc) async for doc in cursor]

        next_cursor = None
        if len(results) > cursor_params.limit:
            results = results[: cursor_params.limit]
            last = results[-1]
            next_cursor = encode_cursor(self._extract_sort_value(last, sort_field), last.id)

        return CursorPage(results=results, count=count, next_cursor=next_cursor)

    async def find_mention_ids_by_cluster(
        self,
        cluster_id: str,
        limit: int,
    ) -> list[EntityMentionIdentifier]:
        cursor = self._collection.find(
            {"current_placement.cluster_id": cluster_id},
            projection={"about_entity_mention": 1, "_id": 0},
        )
        cursor = cursor.limit(limit)
        return [
            EntityMentionIdentifier.model_validate(doc["about_entity_mention"])
            async for doc in cursor
        ]

    async def count_distinct_clusters(self) -> int:
        result = await self._collection.distinct("current_placement.cluster_id")
        return len(result)

    async def average_cluster_size(self) -> float:
        pipeline: list[dict[str, Any]] = [
            {
                "$group": {
                    "_id": "$current_placement.cluster_id",
                    "count": {"$sum": 1},
                }
            },
            {"$group": {"_id": None, "avg": {"$avg": "$count"}}},
        ]
        cursor = await self._collection.aggregate(pipeline)
        result = await cursor.to_list()
        return result[0]["avg"] if result else 0.0
