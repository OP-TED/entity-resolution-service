from typing import Any

from erspec.models.core import Decision, EntityMentionIdentifier

from ers.adapters.mongodb.base import BaseMongoRepository
from ers.application.dtos import (
    DecisionFilters,
    DecisionOrdering,
    PaginatedResult,
    PaginationParams,
)
from ers.application.ports.decision_repository import (
    DecisionRepository as DecisionRepositoryPort,
)


class MongoDecisionRepository(
    BaseMongoRepository[Decision, str],
    DecisionRepositoryPort,
):
    _model_class = Decision
    _id_field = "id"

    def _build_query(self, filters: DecisionFilters) -> dict[str, Any]:
        query: dict[str, Any] = {}

        if filters.entity_type is not None:
            query["about_entity_mention.entity_type"] = filters.entity_type

        placement_range: dict[str, dict[str, float]] = {}
        if filters.confidence_min is not None:
            placement_range.setdefault("current_placement.confidence_score", {})[
                "$gte"
            ] = filters.confidence_min
        if filters.confidence_max is not None:
            placement_range.setdefault("current_placement.confidence_score", {})[
                "$lte"
            ] = filters.confidence_max
        if filters.similarity_min is not None:
            placement_range.setdefault("current_placement.similarity_score", {})[
                "$gte"
            ] = filters.similarity_min
        if filters.similarity_max is not None:
            placement_range.setdefault("current_placement.similarity_score", {})[
                "$lte"
            ] = filters.similarity_max
        query.update(placement_range)

        return query

    def _build_sort(self, ordering: DecisionOrdering | None) -> list[tuple[str, int]]:
        if ordering is None:
            return [("created_at", -1)]

        field_map: dict[DecisionOrdering, tuple[str, int]] = {
            DecisionOrdering.CONFIDENCE_ASC: ("current_placement.confidence_score", 1),
            DecisionOrdering.CONFIDENCE_DESC: (
                "current_placement.confidence_score",
                -1,
            ),
            DecisionOrdering.CREATED_AT_ASC: ("created_at", 1),
            DecisionOrdering.CREATED_AT_DESC: ("created_at", -1),
            DecisionOrdering.UPDATED_AT_ASC: ("updated_at", 1),
            DecisionOrdering.UPDATED_AT_DESC: ("updated_at", -1),
        }
        return [field_map[ordering]]

    async def find_with_filters(
        self,
        filters: DecisionFilters,
        pagination: PaginationParams,
        mention_identifiers: list[EntityMentionIdentifier] | None = None,
    ) -> PaginatedResult[Decision]:
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

        sort = self._build_sort(filters.ordering)
        skip = (pagination.page - 1) * pagination.per_page

        count = await self._collection.count_documents(query)
        cursor = (
            self._collection.find(query)
            .sort(sort)
            .skip(skip)
            .limit(pagination.per_page)
        )
        results = [self._from_document(doc) async for doc in cursor]

        total_pages = (
            (count + pagination.per_page - 1) // pagination.per_page if count > 0 else 0
        )

        return PaginatedResult(
            count=count,
            previous=pagination.page - 1 if pagination.page > 1 else None,
            next=pagination.page + 1 if pagination.page < total_pages else None,
            results=results,
        )
