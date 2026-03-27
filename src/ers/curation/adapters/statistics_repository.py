from abc import ABC, abstractmethod

from erspec.models.core import UserActionType
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

from ers.curation.domain.data_transfer_objects import (
    CurationStatistics,
    RegistryStatistics,
    StatisticsFilters,
)


class StatisticsRepository(ABC):
    """Repository for aggregated statistics queries."""

    @abstractmethod
    async def get_curation_statistics(
        self,
        filters: StatisticsFilters,
    ) -> CurationStatistics:
        """Aggregate curation action counts."""

    @abstractmethod
    async def get_registry_statistics(
        self,
        filters: StatisticsFilters,
    ) -> RegistryStatistics:
        """Aggregate entity mention and canonical entity counts."""


class MongoStatisticsRepository(StatisticsRepository):
    """Aggregates statistics across multiple collections."""

    def __init__(self, database: AsyncDatabase) -> None:
        self._decisions: AsyncCollection = database["decisions"]
        self._user_actions: AsyncCollection = database["user_actions"]
        self._resolution_requests: AsyncCollection = database["resolution_requests"]

    def _build_time_filter(self, filters: StatisticsFilters) -> dict:
        match: dict = {}
        if filters.entity_type is not None:
            match["about_entity_mention.entity_type"] = filters.entity_type
        time_range: dict = {}
        if filters.timeframe_start is not None:
            time_range["$gte"] = filters.timeframe_start
        if filters.timeframe_end is not None:
            time_range["$lte"] = filters.timeframe_end
        if time_range:
            match["created_at"] = time_range
        return match

    async def get_curation_statistics(
        self,
        filters: StatisticsFilters,
    ) -> CurationStatistics:
        match = self._build_time_filter(filters)

        decision_filter: dict = {}
        if filters.entity_type is not None:
            decision_filter["about_entity_mention.entity_type"] = filters.entity_type
        total_decisions = await self._decisions.count_documents(decision_filter)

        pipeline: list[dict] = []
        if match:
            pipeline.append({"$match": match})
        pipeline.append({"$group": {"_id": "$action_type", "count": {"$sum": 1}}})

        counts: dict[str, int] = {}
        cursor = await self._user_actions.aggregate(pipeline)
        async for doc in cursor:
            counts[doc["_id"]] = doc["count"]

        return CurationStatistics(
            total_decisions=total_decisions,
            selected_top=counts.get(UserActionType.ACCEPT_TOP, 0),
            selected_alternative=counts.get(UserActionType.ACCEPT_ALTERNATIVE, 0),
            rejected_all=counts.get(UserActionType.REJECT_ALL, 0),
        )

    async def get_registry_statistics(
        self,
        filters: StatisticsFilters,
    ) -> RegistryStatistics:
        entity_filter: dict = {}
        if filters.entity_type is not None:
            entity_filter["identifiedBy.entity_type"] = filters.entity_type

        total_entity_mentions = await self._resolution_requests.count_documents(entity_filter)

        decision_filter: dict = {}
        if filters.entity_type is not None:
            decision_filter["about_entity_mention.entity_type"] = filters.entity_type

        distinct_clusters = await self._decisions.distinct(
            "current_placement.cluster_id",
            decision_filter,
        )
        total_canonical_entities = len(distinct_clusters)

        avg_pipeline: list[dict] = []
        if decision_filter:
            avg_pipeline.append({"$match": decision_filter})
        avg_pipeline.extend(
            [
                {
                    "$group": {
                        "_id": "$current_placement.cluster_id",
                        "count": {"$sum": 1},
                    }
                },
                {"$group": {"_id": None, "avg": {"$avg": "$count"}}},
            ]
        )
        avg_cursor = await self._decisions.aggregate(avg_pipeline)
        avg_result = await avg_cursor.to_list()
        average_cluster_size = avg_result[0]["avg"] if avg_result else 0.0

        distinct_requests = await self._resolution_requests.distinct(
            "identifiedBy.request_id",
            entity_filter,
        )
        resolution_requests = len(distinct_requests)

        return RegistryStatistics(
            total_entity_mentions=total_entity_mentions,
            total_canonical_entities=total_canonical_entities,
            average_cluster_size=average_cluster_size,
            resolution_requests=resolution_requests,
        )
