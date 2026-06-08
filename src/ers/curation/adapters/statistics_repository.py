from abc import ABC, abstractmethod

from erspec.models.core import UserActionType
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

from ers.curation.domain.data_transfer_objects import (
    CurationStatistics,
    RegistryStatistics,
    StatisticsFilters,
)

_FIELD_SIZE = "size"


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
        self._cluster_sizes: AsyncCollection = database["cluster_sizes"]

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

    async def _get_cluster_distribution(self) -> tuple[float, float, int, int, int]:
        """Compute cluster-size distribution statistics from the cluster_sizes collection.

        Returns a tuple of (average, median, p95, max, singletons_count).

        Reads from the ``cluster_sizes`` projection — one document per cluster —
        keeping the query cheap regardless of the number of decisions.

        Uses Python-side median/p95 computation after collecting all sizes via a
        single ``$group``/``$push`` aggregation, ensuring compatibility with
        FerretDB and environments that do not support ``$percentile`` (MongoDB 7+).

        Returns:
            Tuple (cluster_size_average, cluster_size_median, cluster_size_p95,
            cluster_size_max, cluster_singletons_count) where all values are 0
            when the collection is empty.
        """
        # Singletons: simple count
        singletons_count = await self._cluster_sizes.count_documents({_FIELD_SIZE: 1})

        # Max: sort descending, take first document
        cluster_size_max = 0
        async for doc in self._cluster_sizes.find().sort([(_FIELD_SIZE, -1)]).limit(1):
            cluster_size_max = int(doc[_FIELD_SIZE])

        # Average / median / p95: single aggregation collecting all sizes
        pipeline: list[dict] = [
            {
                "$group": {
                    "_id": None,
                    "avg": {"$avg": f"${_FIELD_SIZE}"},
                    "sizes": {"$push": f"${_FIELD_SIZE}"},
                }
            }
        ]
        agg_cursor = await self._cluster_sizes.aggregate(pipeline)
        agg_results = await agg_cursor.to_list()

        if not agg_results:
            return 0.0, 0.0, 0, 0, 0

        row = agg_results[0]
        avg: float = float(row["avg"])
        sizes: list[int] = sorted(int(s) for s in row["sizes"])
        n = len(sizes)

        # Median: average of two middle values for even n, middle value for odd n
        median = (
            (sizes[n // 2 - 1] + sizes[n // 2]) / 2.0 if n % 2 == 0 else float(sizes[n // 2])
        )

        # p95: nearest-rank method (exclusive), clamped to last index
        p95_idx = min(int(0.95 * n), n - 1)
        p95 = sizes[p95_idx]

        return avg, median, p95, cluster_size_max, singletons_count

    async def get_registry_statistics(
        self,
        filters: StatisticsFilters,
    ) -> RegistryStatistics:
        """Aggregate entity mention and canonical entity counts.

        Args:
            filters: Optional filters for entity type and time window.

        Returns:
            A ``RegistryStatistics`` DTO with all cluster-distribution fields
            sourced from the ``cluster_sizes`` collection.
        """
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

        distinct_requests = await self._resolution_requests.distinct(
            "identifiedBy.request_id",
            entity_filter,
        )
        resolution_requests = len(distinct_requests)

        avg, median, p95, size_max, singletons = await self._get_cluster_distribution()

        return RegistryStatistics(
            total_entity_mentions=total_entity_mentions,
            total_canonical_entities=total_canonical_entities,
            cluster_size_average=avg,
            cluster_size_median=median,
            cluster_size_p95=p95,
            cluster_size_max=size_max,
            cluster_singletons_count=singletons,
            resolution_requests=resolution_requests,
        )
