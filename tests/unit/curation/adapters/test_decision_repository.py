from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from erspec.models.core import EntityMentionIdentifier

from ers.curation.adapters.decision_repository import MongoDecisionCurationRepository
from ers.curation.domain.data_transfer_objects import (
    DecisionFilters,
)
from tests.unit.factories import DecisionFactory, EntityMentionIdentifierFactory


class _MockAsyncCursor:
    def __init__(self, documents: list[dict]):
        self._documents = list(documents)

    def sort(self, *_a, **_kw):
        return self

    def skip(self, *_a, **_kw):
        return self

    def limit(self, *_a, **_kw):
        return self

    def __aiter__(self):
        return _AsyncDocIterator(self._documents)


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
    mock_collection = AsyncMock()
    mock_collection.find = MagicMock(return_value=_MockAsyncCursor([]))
    mock_db.__getitem__.return_value = mock_collection
    repo = MongoDecisionCurationRepository(mock_db)
    return repo, mock_collection


class TestBuildQuery:
    def test_confidence_max_filter(self):
        repo, _ = _make_repo()
        filters = DecisionFilters(confidence_max=0.9)
        result = repo._build_query(filters)
        assert result["current_placement.confidence_score"]["$lte"] == 0.9

    def test_similarity_min_filter(self):
        repo, _ = _make_repo()
        filters = DecisionFilters(similarity_min=0.5)
        result = repo._build_query(filters)
        assert result["current_placement.similarity_score"]["$gte"] == 0.5

    def test_similarity_max_filter(self):
        repo, _ = _make_repo()
        filters = DecisionFilters(similarity_max=0.95)
        result = repo._build_query(filters)
        assert result["current_placement.similarity_score"]["$lte"] == 0.95

    def test_combined_confidence_and_similarity(self):
        repo, _ = _make_repo()
        filters = DecisionFilters(
            confidence_min=0.3,
            confidence_max=0.8,
            similarity_min=0.4,
            similarity_max=0.9,
        )
        result = repo._build_query(filters)
        assert result["current_placement.confidence_score"] == {"$gte": 0.3, "$lte": 0.8}
        assert result["current_placement.similarity_score"] == {"$gte": 0.4, "$lte": 0.9}


class TestBuildCursorCondition:
    def test_ascending_with_none_sort_value(self):
        repo, _ = _make_repo()
        result = repo._build_cursor_condition("created_at", None, "last-id", ascending=True)
        assert "$or" in result
        assert len(result["$or"]) == 2
        assert result["$or"][0] == {"created_at": None, "_id": {"$gt": "last-id"}}
        assert result["$or"][1] == {"created_at": {"$ne": None}}

    def test_descending_with_none_sort_value(self):
        repo, _ = _make_repo()
        result = repo._build_cursor_condition("created_at", None, "last-id", ascending=False)
        assert result == {"created_at": None, "_id": {"$lt": "last-id"}}


class TestExtractSortValue:
    def test_confidence_score_field(self):
        repo, _ = _make_repo()
        decision = DecisionFactory.build()
        result = repo._extract_sort_value(decision, "current_placement.confidence_score")
        assert result == decision.current_placement.confidence_score

    def test_created_at_field(self):
        repo, _ = _make_repo()
        decision = DecisionFactory.build()
        result = repo._extract_sort_value(decision, "created_at")
        assert result == decision.created_at

    def test_updated_at_field(self):
        repo, _ = _make_repo()
        dt = datetime.now(UTC)
        decision = DecisionFactory.build(updated_at=dt)
        result = repo._extract_sort_value(decision, "updated_at")
        assert result == dt

    def test_unknown_field_returns_none(self):
        repo, _ = _make_repo()
        decision = DecisionFactory.build()
        result = repo._extract_sort_value(decision, "unknown_field")
        assert result is None


class TestParseCursorSortValue:
    def test_none_value_returns_none(self):
        repo, _ = _make_repo()
        assert repo._parse_cursor_sort_value(None, "created_at") is None

    def test_datetime_field_parses_isoformat(self):
        repo, _ = _make_repo()
        iso = "2024-06-15T10:30:00"
        result = repo._parse_cursor_sort_value(iso, "created_at")
        assert result == datetime.fromisoformat(iso)

    def test_updated_at_field_parses_isoformat(self):
        repo, _ = _make_repo()
        iso = "2024-06-15T10:30:00"
        result = repo._parse_cursor_sort_value(iso, "updated_at")
        assert result == datetime.fromisoformat(iso)

    def test_numeric_field_returns_value_unchanged(self):
        repo, _ = _make_repo()
        result = repo._parse_cursor_sort_value(0.85, "current_placement.confidence_score")
        assert result == 0.85


class TestFindMentionIdsByCluster:
    async def test_returns_entity_mention_identifiers(self):
        repo, col = _make_repo()
        mention = EntityMentionIdentifierFactory.build()
        mention_doc = mention.model_dump(mode="python")
        col.find = MagicMock(return_value=_MockAsyncCursor([{"about_entity_mention": mention_doc}]))

        result = await repo.find_mention_ids_by_cluster("cluster-1", limit=10)

        assert len(result) == 1
        assert isinstance(result[0], EntityMentionIdentifier)
        col.find.assert_called_once_with(
            {"current_placement.cluster_id": "cluster-1"},
            projection={"about_entity_mention": 1, "_id": 0},
        )


class TestCountDistinctClusters:
    async def test_returns_count(self):
        repo, col = _make_repo()
        col.distinct.return_value = ["cluster-1", "cluster-2", "cluster-3"]

        result = await repo.count_distinct_clusters()

        assert result == 3
        col.distinct.assert_awaited_once_with("current_placement.cluster_id")


class TestAverageClusterSize:
    async def test_returns_average(self):
        repo, col = _make_repo()
        mock_cursor = AsyncMock()
        mock_cursor.to_list.return_value = [{"_id": None, "avg": 2.5}]
        col.aggregate.return_value = mock_cursor

        result = await repo.average_cluster_size()

        assert result == 2.5

    async def test_empty_collection_returns_zero(self):
        repo, col = _make_repo()
        mock_cursor = AsyncMock()
        mock_cursor.to_list.return_value = []
        col.aggregate.return_value = mock_cursor

        result = await repo.average_cluster_size()

        assert result == 0.0
