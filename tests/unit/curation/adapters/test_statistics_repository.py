from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from ers.curation.adapters.statistics_repository import MongoStatisticsRepository
from ers.curation.domain.data_transfer_objects import StatisticsFilters


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

    def getitem(name):
        return {
            "decisions": decisions_col,
            "user_actions": user_actions_col,
            "resolution_requests": resolution_requests_col,
        }[name]

    mock_db.__getitem__.side_effect = getitem
    repo = MongoStatisticsRepository(mock_db)
    return repo, decisions_col, user_actions_col, resolution_requests_col


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
        repo, decisions_col, actions_col, _ = _make_repo()
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
        repo, decisions_col, actions_col, _ = _make_repo()
        decisions_col.count_documents.return_value = 4
        actions_col.aggregate.return_value = _MockAsyncAggregationCursor([])

        result = await repo.get_curation_statistics(StatisticsFilters(entity_type="ORGANISATION"))

        assert result.total_decisions == 4
        assert result.selected_top == 0
        decisions_col.count_documents.assert_awaited_once_with(
            {"about_entity_mention.entity_type": "ORGANISATION"}
        )

    async def test_with_time_filter(self):
        repo, decisions_col, actions_col, _ = _make_repo()
        dt = datetime(2024, 1, 1)
        decisions_col.count_documents.return_value = 0
        actions_col.aggregate.return_value = _MockAsyncAggregationCursor([])

        await repo.get_curation_statistics(StatisticsFilters(timeframe_start=dt))

        pipeline = actions_col.aggregate.call_args[0][0]
        assert {"$match": {"created_at": {"$gte": dt}}} in pipeline


class TestGetRegistryStatistics:
    async def test_no_filters(self):
        repo, decisions_col, _, requests_col = _make_repo()
        requests_col.count_documents.return_value = 100
        decisions_col.distinct.return_value = ["c1", "c2"]
        avg_cursor = AsyncMock()
        avg_cursor.to_list.return_value = [{"_id": None, "avg": 3.5}]
        decisions_col.aggregate.return_value = avg_cursor
        requests_col.distinct.return_value = ["r1", "r2", "r3"]

        result = await repo.get_registry_statistics(StatisticsFilters())

        assert result.total_entity_mentions == 100
        assert result.total_canonical_entities == 2
        assert result.average_cluster_size == 3.5
        assert result.resolution_requests == 3

    async def test_with_entity_type_filter(self):
        repo, decisions_col, _, requests_col = _make_repo()
        requests_col.count_documents.return_value = 50
        decisions_col.distinct.return_value = ["c1"]
        avg_cursor = AsyncMock()
        avg_cursor.to_list.return_value = [{"_id": None, "avg": 2.0}]
        decisions_col.aggregate.return_value = avg_cursor
        requests_col.distinct.return_value = ["r1"]

        result = await repo.get_registry_statistics(StatisticsFilters(entity_type="PROCEDURE"))

        assert result.total_entity_mentions == 50
        requests_col.count_documents.assert_awaited_once_with(
            {"identifiedBy.entity_type": "PROCEDURE"}
        )
        decisions_col.distinct.assert_awaited_once_with(
            "current_placement.cluster_id",
            {"about_entity_mention.entity_type": "PROCEDURE"},
        )

    async def test_empty_collection_returns_zero_average(self):
        repo, decisions_col, _, requests_col = _make_repo()
        requests_col.count_documents.return_value = 0
        decisions_col.distinct.return_value = []
        avg_cursor = AsyncMock()
        avg_cursor.to_list.return_value = []
        decisions_col.aggregate.return_value = avg_cursor
        requests_col.distinct.return_value = []

        result = await repo.get_registry_statistics(StatisticsFilters())

        assert result.average_cluster_size == 0.0
        assert result.total_canonical_entities == 0
