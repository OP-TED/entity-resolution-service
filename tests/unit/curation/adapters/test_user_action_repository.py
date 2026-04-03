from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from erspec.models.core import UserActionType

from ers.commons.domain.cursor import encode_cursor
from ers.commons.domain.data_transfer_objects import CursorParams
from ers.curation.adapters.user_action_repository import MongoUserActionCurationRepository
from ers.curation.domain.data_transfer_objects import BaseOrdering, UserActionFilters
from tests.unit.factories import UserActionFactory


def _async_iter(items: list):
    """Return an object that satisfies `async for doc in cursor` with chained sort/limit."""

    class _AsyncCursor:
        def __init__(self, data):
            self._data = list(data)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._data:
                raise StopAsyncIteration
            return self._data.pop(0)

        def sort(self, _keys):
            return self

        def limit(self, _n):
            return self

    return _AsyncCursor(items)


@pytest.fixture
def collection() -> AsyncMock:
    col = AsyncMock()
    col.find = MagicMock(return_value=_async_iter([]))
    col.count_documents.return_value = 0
    return col


@pytest.fixture
def repo(collection: AsyncMock) -> MongoUserActionCurationRepository:
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=collection)
    return MongoUserActionCurationRepository(db)


class TestBuildFilterQuery:
    def test_none_filters_returns_empty(self) -> None:
        assert MongoUserActionCurationRepository._build_filter_query(None) == {}

    def test_action_type_filter(self) -> None:
        filters = UserActionFilters(action_type=UserActionType.ACCEPT_TOP)
        result = MongoUserActionCurationRepository._build_filter_query(filters)
        assert result == {"action_type": "ACCEPT_TOP"}

    def test_actor_filter(self) -> None:
        filters = UserActionFilters(actor="curator@example.com")
        result = MongoUserActionCurationRepository._build_filter_query(filters)
        assert result == {"actor": "curator@example.com"}

    def test_time_range_start_only(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        filters = UserActionFilters(time_range_start=start)
        result = MongoUserActionCurationRepository._build_filter_query(filters)
        assert result == {"created_at": {"$gte": start}}

    def test_time_range_end_only(self) -> None:
        end = datetime(2026, 12, 31, tzinfo=UTC)
        filters = UserActionFilters(time_range_end=end)
        result = MongoUserActionCurationRepository._build_filter_query(filters)
        assert result == {"created_at": {"$lte": end}}

    def test_full_time_range(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 12, 31, tzinfo=UTC)
        filters = UserActionFilters(time_range_start=start, time_range_end=end)
        result = MongoUserActionCurationRepository._build_filter_query(filters)
        assert result == {"created_at": {"$gte": start, "$lte": end}}

    def test_combined_filters(self) -> None:
        start = datetime(2026, 3, 1, tzinfo=UTC)
        filters = UserActionFilters(
            action_type=UserActionType.REJECT_ALL,
            actor="admin@test.com",
            time_range_start=start,
        )
        result = MongoUserActionCurationRepository._build_filter_query(filters)
        assert result["action_type"] == "REJECT_ALL"
        assert result["actor"] == "admin@test.com"
        assert result["created_at"] == {"$gte": start}


class TestGetSortInfo:
    def test_default_ordering(self, repo: MongoUserActionCurationRepository) -> None:
        field, ascending = repo._get_sort_info(None)
        assert field == "created_at"
        assert ascending is False

    def test_no_ordering_in_filters(self, repo: MongoUserActionCurationRepository) -> None:
        filters = UserActionFilters(actor="someone")
        field, ascending = repo._get_sort_info(filters)
        assert field == "created_at"
        assert ascending is False

    def test_created_at_asc(self, repo: MongoUserActionCurationRepository) -> None:
        filters = UserActionFilters(ordering=BaseOrdering.CREATED_AT_ASC)
        field, ascending = repo._get_sort_info(filters)
        assert field == "created_at"
        assert ascending is True

    def test_created_at_desc(self, repo: MongoUserActionCurationRepository) -> None:
        filters = UserActionFilters(ordering=BaseOrdering.CREATED_AT_DESC)
        field, ascending = repo._get_sort_info(filters)
        assert field == "created_at"
        assert ascending is False


class TestBuildCursorCondition:
    def test_null_sort_value_descending(self, repo: MongoUserActionCurationRepository) -> None:
        result = repo._build_cursor_condition(sort_value=None, last_id="abc", ascending=False)
        assert result == {"created_at": None, "_id": {"$lt": "abc"}}

    def test_null_sort_value_ascending(self, repo: MongoUserActionCurationRepository) -> None:
        result = repo._build_cursor_condition(sort_value=None, last_id="abc", ascending=True)
        assert result == {"created_at": None, "_id": {"$gt": "abc"}}

    def test_with_sort_value_descending(self, repo: MongoUserActionCurationRepository) -> None:
        ts = datetime(2026, 3, 15, tzinfo=UTC)
        result = repo._build_cursor_condition(sort_value=ts, last_id="xyz", ascending=False)
        assert result == {
            "$or": [
                {"created_at": {"$lt": ts}},
                {"created_at": ts, "_id": {"$lt": "xyz"}},
            ]
        }

    def test_with_sort_value_ascending(self, repo: MongoUserActionCurationRepository) -> None:
        ts = datetime(2026, 3, 15, tzinfo=UTC)
        result = repo._build_cursor_condition(sort_value=ts, last_id="xyz", ascending=True)
        assert result == {
            "$or": [
                {"created_at": {"$gt": ts}},
                {"created_at": ts, "_id": {"$gt": "xyz"}},
            ]
        }


class TestFindWithCursor:
    async def test_no_cursor_no_filters(
        self,
        repo: MongoUserActionCurationRepository,
        collection: AsyncMock,
    ) -> None:
        action = UserActionFactory.build()
        doc = action.model_dump(exclude={"object_description"})
        doc["_id"] = doc.pop("id")
        collection.find.return_value = _async_iter([doc])
        collection.count_documents.return_value = 1

        result = await repo.find_with_cursor(CursorParams(limit=10))

        assert len(result.results) == 1
        assert result.results[0].id == action.id
        assert result.count == 1
        assert result.next_cursor is None
        collection.find.assert_called_once()
        collection.count_documents.assert_called_once_with({})

    async def test_returns_next_cursor_when_more_results(
        self,
        repo: MongoUserActionCurationRepository,
        collection: AsyncMock,
    ) -> None:
        actions = UserActionFactory.batch(3)
        docs = []
        for a in actions:
            d = a.model_dump(exclude={"object_description"})
            d["_id"] = d.pop("id")
            docs.append(d)
        collection.find.return_value = _async_iter(docs)
        collection.count_documents.return_value = 10

        result = await repo.find_with_cursor(CursorParams(limit=2))

        assert len(result.results) == 2
        assert result.count == 10
        assert result.next_cursor is not None

    async def test_no_next_cursor_on_exact_page(
        self,
        repo: MongoUserActionCurationRepository,
        collection: AsyncMock,
    ) -> None:
        actions = UserActionFactory.batch(2)
        docs = []
        for a in actions:
            d = a.model_dump(exclude={"object_description"})
            d["_id"] = d.pop("id")
            docs.append(d)
        collection.find.return_value = _async_iter(docs)

        result = await repo.find_with_cursor(CursorParams(limit=2))

        assert len(result.results) == 2
        assert result.next_cursor is None

    async def test_with_cursor_applies_condition(
        self,
        repo: MongoUserActionCurationRepository,
        collection: AsyncMock,
    ) -> None:
        collection.find.return_value = _async_iter([])
        ts = datetime(2026, 3, 15, tzinfo=UTC)
        cursor = encode_cursor(ts, "last-id")

        await repo.find_with_cursor(CursorParams(cursor=cursor, limit=5))

        query = collection.find.call_args[0][0]
        assert "$and" in query

    async def test_with_cursor_none_sort_value(
        self,
        repo: MongoUserActionCurationRepository,
        collection: AsyncMock,
    ) -> None:
        collection.find.return_value = _async_iter([])
        cursor = encode_cursor(None, "last-id")

        await repo.find_with_cursor(CursorParams(cursor=cursor, limit=5))

        query = collection.find.call_args[0][0]
        assert "$and" in query

    async def test_with_filters(
        self,
        repo: MongoUserActionCurationRepository,
        collection: AsyncMock,
    ) -> None:
        collection.find.return_value = _async_iter([])
        collection.count_documents.return_value = 5
        filters = UserActionFilters(actor="curator@test.com")

        result = await repo.find_with_cursor(CursorParams(limit=10), filters)

        query = collection.find.call_args[0][0]
        assert query["actor"] == "curator@test.com"
        collection.count_documents.assert_called_once_with({"actor": "curator@test.com"})
        assert result.count == 5

    async def test_with_ordering_asc(
        self,
        repo: MongoUserActionCurationRepository,
        collection: AsyncMock,
    ) -> None:
        collection.find.return_value = _async_iter([])
        filters = UserActionFilters(ordering=BaseOrdering.CREATED_AT_ASC)

        await repo.find_with_cursor(CursorParams(limit=10), filters)

        # sort is chained, so verify find was called
        collection.find.assert_called_once()

    async def test_empty_result(
        self,
        repo: MongoUserActionCurationRepository,
        collection: AsyncMock,
    ) -> None:
        collection.find.return_value = _async_iter([])
        collection.count_documents.return_value = 0

        result = await repo.find_with_cursor(CursorParams(limit=10))

        assert result.results == []
        assert result.count == 0
        assert result.next_cursor is None
