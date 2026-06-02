from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from ers.curation.adapters.statistics_repository import MongoStatisticsRepository
from ers.curation.domain.data_transfer_objects import StatisticsFilters

pytestmark = pytest.mark.asyncio


class _MockAsyncAggregationCursor:
    def __init__(self, documents: list[dict]):
        self._documents = list(documents)

    def __aiter__(self):
        return _AsyncDocIterator(self._documents)

    async def to_list(self):
        return self._documents


class _AsyncDocIterator:
    def __init__(self, docs):
        self._docs = docs
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._docs):
            raise StopAsyncIteration
        doc = self._docs[self._index]
        self._index += 1
        return doc


def _make_repo():
    mock_db = MagicMock()
    decisions_col = AsyncMock()
    user_actions_col = AsyncMock()
    resolution_requests_col = AsyncMock()
    cluster_sizes_col = AsyncMock()

    def getitem(name):
        return {
            "decisions": decisions_col,
            "user_actions": user_actions_col,
            "resolution_requests": resolution_requests_col,
            "cluster_sizes": cluster_sizes_col,
        }[name]

    mock_db.__getitem__.side_effect = getitem
    repo = MongoStatisticsRepository(mock_db)
    return repo, decisions_col, user_actions_col, resolution_requests_col, cluster_sizes_col


class TestBuildTimeFilter:
    def test_empty_filters(self):
        repo, *_ = _make_repo()
        result = repo._build_time_filter(StatisticsFilters())
        assert result == {}

    def test_entity_type_filter(self):
        repo, *_ = _make_repo()
        result = repo._build_time_filter(StatisticsFilters(entity_type="ORGANISATION"))
        assert result == {"about_entity_mention.entity_type": "ORGANISATION"}

    def test_timeframe_start(self):
        repo, *_ = _make_repo()
        dt = datetime(2024, 1, 1)
        result = repo._build_time_filter(StatisticsFilters(timeframe_start=dt))
        assert result == {"created_at": {"$gte": dt}}

    def test_timeframe_end(self):
        repo, *_ = _make_repo()
        dt = datetime(2024, 12, 31)
        result = repo._build_time_filter(StatisticsFilters(timeframe_end=dt))
        assert result == {"created_at": {"$lte": dt}}

    def test_full_timeframe(self):
        repo, *_ = _make_repo()
        start, end = datetime(2024, 1, 1), datetime(2024, 12, 31)
        result = repo._build_time_filter(
            StatisticsFilters(timeframe_start=start, timeframe_end=end)
        )
        assert result == {"created_at": {"$gte": start, "$lte": end}}

    def test_entity_type_with_timeframe(self):
        repo, *_ = _make_repo()
        dt = datetime(2024, 6, 1)
        result = repo._build_time_filter(
            StatisticsFilters(entity_type="PROCEDURE", timeframe_start=dt)
        )
        assert result == {
            "about_entity_mention.entity_type": "PROCEDURE",
            "created_at": {"$gte": dt},
        }


class TestGetCurationStatistics:
    async def test_no_filters(self):
        repo, decisions_col, actions_col, *_ = _make_repo()
        decisions_col.count_documents.return_value = 10
        actions_col.aggregate.return_value = _MockAsyncAggregationCursor(
            [
                {"_id": "ACCEPT_TOP", "count": 5},
                {"_id": "ACCEPT_ALTERNATIVE", "count": 3},
                {"_id": "REJECT_ALL", "count": 2},
            ]
        )

        result = await repo.get_curation_statistics(StatisticsFilters())

        assert result.total_decisions == 10
        assert result.selected_top == 5
        assert result.selected_alternative == 3
        assert result.rejected_all == 2

    async def test_with_entity_type_filter(self):
        repo, decisions_col, actions_col, *_ = _make_repo()
        decisions_col.count_documents.return_value = 4
        actions_col.aggregate.return_value = _MockAsyncAggregationCursor([])

        result = await repo.get_curation_statistics(StatisticsFilters(entity_type="ORGANISATION"))

        assert result.total_decisions == 4
        assert result.selected_top == 0
        decisions_col.count_documents.assert_awaited_once_with(
            {"about_entity_mention.entity_type": "ORGANISATION"}
        )

    async def test_with_time_filter(self):
        repo, decisions_col, actions_col, *_ = _make_repo()
        dt = datetime(2024, 1, 1)
        decisions_col.count_documents.return_value = 0
        actions_col.aggregate.return_value = _MockAsyncAggregationCursor([])

        await repo.get_curation_statistics(StatisticsFilters(timeframe_start=dt))

        pipeline = actions_col.aggregate.call_args[0][0]
        assert {"$match": {"created_at": {"$gte": dt}}} in pipeline


# ---------------------------------------------------------------------------
# Registry statistics — new cluster_sizes-based fields
# ---------------------------------------------------------------------------


class TestGetRegistryStatistics:
    """All cluster distribution fields read from cluster_sizes, not decisions."""

    def _setup_cluster_sizes_col(self, cluster_sizes_col: AsyncMock, sizes: list[int]) -> None:
        """Configure the cluster_sizes mock for a given list of cluster sizes.

        ``find`` in the pymongo async driver is a synchronous call that returns a cursor
        object — it is NOT a coroutine.  We therefore configure ``cluster_sizes_col.find``
        as a plain ``MagicMock`` so the chained ``.sort().limit()`` returns a synchronous
        iterable (async-iterable via ``__aiter__``), matching the real driver behaviour.
        """
        # count_documents for singletons
        cluster_sizes_col.count_documents.return_value = sum(1 for s in sizes if s == 1)

        # find().sort().limit(1) — find must be a regular (non-async) callable
        # so that .sort() and .limit() can be chained synchronously.
        max_size = max(sizes) if sizes else 0
        max_doc = [{"size": max_size}] if sizes else []

        async def _aiter_max(_self):
            for doc in max_doc:
                yield doc

        limit_mock = MagicMock()
        limit_mock.__aiter__ = _aiter_max
        sort_mock = MagicMock()
        sort_mock.limit.return_value = limit_mock
        find_mock = MagicMock()
        find_mock.sort.return_value = sort_mock
        # Override the AsyncMock's .find to be a plain synchronous MagicMock
        cluster_sizes_col.find = MagicMock(return_value=find_mock)

        # aggregate for avg/median/p95 — returns all sizes as a list
        if sizes:
            sorted_sizes = sorted(sizes)
            n = len(sorted_sizes)
            avg = sum(sizes) / n
            agg_result = [{"avg": avg, "sizes": sizes}]
        else:
            agg_result = []

        cluster_sizes_col.aggregate.return_value = _MockAsyncAggregationCursor(agg_result)

    def _setup_decisions_and_requests(
        self,
        decisions_col: AsyncMock,
        requests_col: AsyncMock,
        total_mentions: int = 100,
        distinct_clusters: list[str] | None = None,
        resolution_requests: int = 10,
    ) -> None:
        requests_col.count_documents.return_value = total_mentions
        decisions_col.distinct.return_value = distinct_clusters or []
        requests_col.distinct.return_value = [f"r{i}" for i in range(resolution_requests)]

    async def test_no_filters(self):
        repo, decisions_col, _, requests_col, cluster_sizes_col = _make_repo()
        self._setup_decisions_and_requests(
            decisions_col, requests_col, total_mentions=100, distinct_clusters=["c1", "c2"], resolution_requests=3
        )
        self._setup_cluster_sizes_col(cluster_sizes_col, [1, 1, 1, 4, 7, 12, 50])

        result = await repo.get_registry_statistics(StatisticsFilters())

        assert result.total_entity_mentions == 100
        assert result.total_canonical_entities == 2
        assert result.resolution_requests == 3
        # cluster distribution — sourced from cluster_sizes
        assert result.cluster_singletons_count == 3
        assert result.cluster_size_max == 50
        assert abs(result.cluster_size_average - 76 / 7) < 0.001
        assert result.cluster_size_median == 4.0
        assert result.cluster_size_p95 == 50

    async def test_reads_cluster_sizes_not_decisions_for_distribution(self):
        """Cluster distribution fields must NOT aggregate decisions collection."""
        repo, decisions_col, _, requests_col, cluster_sizes_col = _make_repo()
        self._setup_decisions_and_requests(decisions_col, requests_col)
        self._setup_cluster_sizes_col(cluster_sizes_col, [2, 4])

        await repo.get_registry_statistics(StatisticsFilters())

        # cluster_sizes_col must be queried for distribution stats
        cluster_sizes_col.count_documents.assert_awaited_once()
        cluster_sizes_col.aggregate.assert_called_once()
        # decisions collection must NOT be used for distribution (only distinct clusters)
        decisions_col.aggregate.assert_not_called()

    async def test_all_singletons(self):
        """All-singleton registry: [1, 1, 1, 1]."""
        repo, decisions_col, _, requests_col, cluster_sizes_col = _make_repo()
        self._setup_decisions_and_requests(decisions_col, requests_col, distinct_clusters=["c1", "c2", "c3", "c4"])
        self._setup_cluster_sizes_col(cluster_sizes_col, [1, 1, 1, 1])

        result = await repo.get_registry_statistics(StatisticsFilters())

        assert result.cluster_singletons_count == 4
        assert result.cluster_size_max == 1
        assert result.cluster_size_median == 1.0
        assert result.cluster_size_p95 == 1
        assert result.cluster_size_average == 1.0

    async def test_single_cluster(self):
        """Single cluster of size 42."""
        repo, decisions_col, _, requests_col, cluster_sizes_col = _make_repo()
        self._setup_decisions_and_requests(decisions_col, requests_col, distinct_clusters=["c1"])
        self._setup_cluster_sizes_col(cluster_sizes_col, [42])

        result = await repo.get_registry_statistics(StatisticsFilters())

        assert result.cluster_singletons_count == 0
        assert result.cluster_size_max == 42
        assert result.cluster_size_median == 42.0
        assert result.cluster_size_p95 == 42
        assert result.cluster_size_average == 42.0

    async def test_even_distribution(self):
        """Even-sized distribution [2, 4, 6, 8] → median = 5.0."""
        repo, decisions_col, _, requests_col, cluster_sizes_col = _make_repo()
        self._setup_decisions_and_requests(decisions_col, requests_col, distinct_clusters=["c1", "c2", "c3", "c4"])
        self._setup_cluster_sizes_col(cluster_sizes_col, [2, 4, 6, 8])

        result = await repo.get_registry_statistics(StatisticsFilters())

        assert result.cluster_singletons_count == 0
        assert result.cluster_size_max == 8
        assert result.cluster_size_median == 5.0
        assert result.cluster_size_average == 5.0

    async def test_distribution_with_ties(self):
        """Distribution with ties [1, 1, 5, 5, 5, 10]."""
        repo, decisions_col, _, requests_col, cluster_sizes_col = _make_repo()
        self._setup_decisions_and_requests(decisions_col, requests_col, distinct_clusters=["c1", "c2", "c3", "c4", "c5", "c6"])
        self._setup_cluster_sizes_col(cluster_sizes_col, [1, 1, 5, 5, 5, 10])

        result = await repo.get_registry_statistics(StatisticsFilters())

        assert result.cluster_singletons_count == 2
        assert result.cluster_size_max == 10
        assert result.cluster_size_average == pytest.approx(27 / 6, abs=0.001)

    async def test_empty_cluster_sizes_returns_zeros(self):
        """Empty cluster_sizes collection → all distribution fields are zero."""
        repo, decisions_col, _, requests_col, cluster_sizes_col = _make_repo()
        requests_col.count_documents.return_value = 0
        decisions_col.distinct.return_value = []
        requests_col.distinct.return_value = []
        # Empty cluster_sizes: reuse helper with empty list
        self._setup_cluster_sizes_col(cluster_sizes_col, [])

        result = await repo.get_registry_statistics(StatisticsFilters())

        assert result.cluster_size_average == 0.0
        assert result.cluster_size_median == 0.0
        assert result.cluster_size_p95 == 0
        assert result.cluster_size_max == 0
        assert result.cluster_singletons_count == 0
        assert result.total_canonical_entities == 0
