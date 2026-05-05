"""Unit tests for MongoDecisionRepository (mocked MongoDB collection)."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers.commons.domain.data_transfer_objects import CursorParams
from ers.commons.domain.exceptions import InvalidCursorError
from ers.resolution_decision_store.adapters.decision_repository import (
    MongoDecisionRepository,
)
from ers.resolution_decision_store.adapters.provisional_id import (
    derive_provisional_cluster_id,
)
from ers.resolution_decision_store.domain.errors import (
    RepositoryConnectionError,
    RepositoryOperationError,
    StaleOutcomeError,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_identifier(source_id="s1", request_id="r1", entity_type="Person"):
    return EntityMentionIdentifier(source_id=source_id, request_id=request_id, entity_type=entity_type)


def make_cluster(cluster_id="c1"):
    return ClusterReference(cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85)


def make_doc(now, triad_hash=None, cluster_id="c1"):
    triad_hash = triad_hash or derive_provisional_cluster_id(make_identifier())
    return {
        "_id": triad_hash,
        "about_entity_mention": {"source_id": "s1", "request_id": "r1", "entity_type": "Person"},
        "current_placement": {"cluster_id": cluster_id, "confidence_score": 0.9, "similarity_score": 0.85},
        "candidates": [],
        "created_at": now,
        "updated_at": now,
    }


@pytest.fixture()
def mock_collection():
    return AsyncMock()


@pytest.fixture()
def mock_database(mock_collection):
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=mock_collection)
    return db


@pytest.fixture()
def repo(mock_database):
    return MongoDecisionRepository(mock_database)


# ── upsert_decision ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_returns_decision_on_success(repo, mock_collection):
    """Insert path: pre-read returns None, find_one_and_update returns the new doc."""
    now = datetime.now(UTC)
    # Pre-read (insert path): no existing doc
    mock_collection.find_one = AsyncMock(return_value=None)
    mock_collection.find_one_and_update = AsyncMock(return_value=make_doc(now))
    result = await repo.upsert_decision(make_identifier(), make_cluster(), [], now)
    assert isinstance(result, Decision)
    assert result.current_placement.cluster_id == "c1"


@pytest.mark.asyncio
async def test_upsert_sets_id_from_triad_hash(repo, mock_collection):
    """Insert path: pre-read returns None; returned doc has the expected triad hash as id."""
    now = datetime.now(UTC)
    expected_hash = derive_provisional_cluster_id(make_identifier())
    mock_collection.find_one = AsyncMock(return_value=None)
    mock_collection.find_one_and_update = AsyncMock(return_value=make_doc(now, triad_hash=expected_hash))
    result = await repo.upsert_decision(make_identifier(), make_cluster(), [], now)
    assert result.id == expected_hash


@pytest.mark.asyncio
async def test_upsert_raises_stale_when_result_is_none(repo, mock_collection):
    """Update path: existing doc present; stale filter rejects → returns None → StaleOutcomeError."""
    now = datetime.now(UTC)
    older = now - timedelta(seconds=1)
    existing = make_doc(now)
    # Pre-read (update path): existing doc found
    # Second find_one called by _fetch_existing_and_raise_stale
    mock_collection.find_one = AsyncMock(side_effect=[existing, existing])
    mock_collection.find_one_and_update = AsyncMock(return_value=None)
    with pytest.raises(StaleOutcomeError):
        await repo.upsert_decision(make_identifier(), make_cluster(), [], older)


@pytest.mark.asyncio
async def test_upsert_raises_operation_error_when_no_existing_doc(repo, mock_collection):
    """Insert path: find_one_and_update returns None (race) and no existing doc → OperationError."""
    now = datetime.now(UTC)
    # Pre-read: no existing doc (insert path)
    # Second find_one: still no doc (race condition, no stale)
    mock_collection.find_one = AsyncMock(side_effect=[None, None])
    mock_collection.find_one_and_update = AsyncMock(return_value=None)
    with pytest.raises(RepositoryOperationError):
        await repo.upsert_decision(make_identifier(), make_cluster(), [], now)


@pytest.mark.asyncio
async def test_upsert_wraps_connection_failure(repo, mock_collection):
    """Insert path: ConnectionFailure on find_one_and_update → RepositoryConnectionError."""
    from pymongo.errors import ConnectionFailure
    # Pre-read: no existing doc
    mock_collection.find_one = AsyncMock(return_value=None)
    mock_collection.find_one_and_update = AsyncMock(side_effect=ConnectionFailure("down"))
    with pytest.raises(RepositoryConnectionError):
        await repo.upsert_decision(make_identifier(), make_cluster(), [], datetime.now(UTC))


# ── find_by_triad ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_by_triad_returns_decision_when_found(repo, mock_collection):
    now = datetime.now(UTC)
    mock_collection.find_one = AsyncMock(return_value=make_doc(now))
    result = await repo.find_by_triad(make_identifier())
    assert isinstance(result, Decision)


@pytest.mark.asyncio
async def test_find_by_triad_returns_none_when_missing(repo, mock_collection):
    mock_collection.find_one = AsyncMock(return_value=None)
    result = await repo.find_by_triad(make_identifier())
    assert result is None


@pytest.mark.asyncio
async def test_find_by_triad_queries_by_triad_hash(repo, mock_collection):
    mock_collection.find_one = AsyncMock(return_value=None)
    expected_hash = derive_provisional_cluster_id(make_identifier())
    await repo.find_by_triad(make_identifier())
    mock_collection.find_one.assert_called_once_with({"_id": expected_hash})


# ── find_with_filters (unfiltered bulk pagination) ────────────────────────────

@pytest.mark.asyncio
async def test_find_with_filters_first_page_no_cursor(repo, mock_collection):
    now = datetime.now(UTC)
    docs = [make_doc(now + timedelta(seconds=i), triad_hash=f"hash{i}") for i in range(3)]

    async def async_generator():
        for doc in docs:
            yield doc

    cursor_mock = MagicMock()
    cursor_mock.sort.return_value = cursor_mock
    cursor_mock.limit.return_value = cursor_mock
    cursor_mock.__aiter__ = lambda self: async_generator()

    mock_collection.find = MagicMock(return_value=cursor_mock)

    page = await repo.find_with_filters(filters=None, cursor_params=CursorParams(cursor=None, limit=3))
    assert len(page.results) == 3
    assert page.next_cursor is None


@pytest.mark.asyncio
async def test_find_with_filters_returns_next_cursor_when_more_results(repo, mock_collection):
    now = datetime.now(UTC)
    # Return page_size+1 docs to signal more pages
    docs = [make_doc(now + timedelta(seconds=i), triad_hash=f"hash{i}") for i in range(4)]

    async def async_generator():
        for doc in docs:
            yield doc

    cursor_mock = MagicMock()
    cursor_mock.sort.return_value = cursor_mock
    cursor_mock.limit.return_value = cursor_mock
    cursor_mock.__aiter__ = lambda self: async_generator()

    mock_collection.find = MagicMock(return_value=cursor_mock)
    page = await repo.find_with_filters(filters=None, cursor_params=CursorParams(cursor=None, limit=3))
    assert len(page.results) == 3
    assert page.next_cursor is not None


@pytest.mark.asyncio
async def test_find_with_filters_raises_invalid_cursor_on_bad_input(repo, mock_collection):
    with pytest.raises(InvalidCursorError):
        await repo.find_with_filters(filters=None, cursor_params=CursorParams(cursor="not-valid-base64!!!", limit=10))


@pytest.mark.asyncio
async def test_find_with_filters_empty_collection_returns_empty_page(repo, mock_collection):
    async def async_generator():
        return
        yield  # make it an async generator

    cursor_mock = MagicMock()
    cursor_mock.sort.return_value = cursor_mock
    cursor_mock.limit.return_value = cursor_mock
    cursor_mock.__aiter__ = lambda self: async_generator()

    mock_collection.find = MagicMock(return_value=cursor_mock)

    page = await repo.find_with_filters(filters=None, cursor_params=CursorParams(cursor=None, limit=3))
    assert len(page.results) == 0
    assert page.next_cursor is None


# ── find_mention_ids_by_cluster ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_mention_ids_by_cluster_returns_identifiers(repo, mock_collection):
    docs = [
        {"about_entity_mention": {"source_id": "s1", "request_id": "r1", "entity_type": "Person"}},
        {"about_entity_mention": {"source_id": "s2", "request_id": "r2", "entity_type": "Person"}},
    ]

    async def async_generator():
        for doc in docs:
            yield doc

    cursor_mock = MagicMock()
    cursor_mock.limit.return_value = cursor_mock
    cursor_mock.__aiter__ = lambda self: async_generator()
    mock_collection.find = MagicMock(return_value=cursor_mock)

    result = await repo.find_mention_ids_by_cluster("cluster-abc", limit=10)
    assert len(result) == 2
    assert result[0].source_id == "s1"
    assert result[1].source_id == "s2"


@pytest.mark.asyncio
async def test_find_mention_ids_by_cluster_queries_by_cluster_id(repo, mock_collection):
    async def async_generator():
        return
        yield

    cursor_mock = MagicMock()
    cursor_mock.limit.return_value = cursor_mock
    cursor_mock.__aiter__ = lambda self: async_generator()
    mock_collection.find = MagicMock(return_value=cursor_mock)

    await repo.find_mention_ids_by_cluster("target-cluster", limit=5)
    mock_collection.find.assert_called_once()
    call_args = mock_collection.find.call_args
    assert call_args[0][0]["current_placement.cluster_id"] == "target-cluster"


# ── upsert_decision: insert vs update path ────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_insert_path_omits_updated_at(repo, mock_collection):
    """On first insert (no existing doc), updated_at must NOT be set in $set."""
    now = datetime.now(UTC)
    # find_one returns None → insert path
    mock_collection.find_one = AsyncMock(return_value=None)
    mock_collection.find_one_and_update = AsyncMock(return_value=make_doc(now))

    await repo.upsert_decision(make_identifier(), make_cluster(), [], now)

    call_args = mock_collection.find_one_and_update.call_args
    # The second positional arg (index 1) is the update doc
    update_doc = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("update")
    assert update_doc is not None, "find_one_and_update was not called with an update doc"
    assert "updated_at" not in update_doc.get("$set", {}), (
        "Insert path must not set updated_at in $set"
    )
    assert "created_at" in update_doc.get("$setOnInsert", {}), (
        "Insert path must set created_at in $setOnInsert"
    )


@pytest.mark.asyncio
async def test_upsert_update_path_sets_updated_at(repo, mock_collection):
    """On update (existing doc present), updated_at MUST be set in $set."""
    now = datetime.now(UTC)
    existing = make_doc(now - timedelta(seconds=10))
    # find_one returns existing doc → update path
    mock_collection.find_one = AsyncMock(return_value=existing)
    updated = make_doc(now)
    mock_collection.find_one_and_update = AsyncMock(return_value=updated)

    await repo.upsert_decision(make_identifier(), make_cluster(), [], now)

    call_args = mock_collection.find_one_and_update.call_args
    update_doc = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("update")
    assert update_doc is not None, "find_one_and_update was not called with an update doc"
    assert "updated_at" in update_doc.get("$set", {}), (
        "Update path must set updated_at in $set"
    )


@pytest.mark.asyncio
async def test_upsert_stale_filter_accepts_none_when_incoming_after_created_at(
    repo, mock_collection
):
    """Existing doc with updated_at=None: write succeeds when incoming > created_at."""
    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC)
    existing_with_none = {**make_doc(t1), "updated_at": None}
    mock_collection.find_one = AsyncMock(return_value=existing_with_none)
    mock_collection.find_one_and_update = AsyncMock(return_value=make_doc(t2))

    # Incoming t2 > stored created_at t1 → fresh, must NOT raise.
    result = await repo.upsert_decision(make_identifier(), make_cluster("c2"), [], t2)
    assert result is not None


@pytest.mark.asyncio
async def test_upsert_stale_filter_rejects_when_updated_at_none_and_incoming_older(
    repo, mock_collection
):
    """R2: updated_at=None + incoming <= created_at → StaleOutcomeError.

    Out-of-order arrival: a newer outcome was inserted first (created_at=t2),
    a later-arriving older outcome (timestamp=t1 < t2) must NOT overwrite.
    """
    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC)
    existing_with_none = {**make_doc(t2), "updated_at": None}
    # find_one called twice: once for pre-read, once for stale fetch.
    mock_collection.find_one = AsyncMock(side_effect=[existing_with_none, existing_with_none])
    mock_collection.find_one_and_update = AsyncMock(return_value=None)

    with pytest.raises(StaleOutcomeError):
        await repo.upsert_decision(make_identifier(), make_cluster("c2"), [], t1)


@pytest.mark.asyncio
async def test_upsert_stale_filter_rejects_regression(repo, mock_collection):
    """Existing doc with updated_at=t2; incoming updated_at=t1 < t2 → StaleOutcomeError."""
    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC)
    existing = {**make_doc(t2), "updated_at": t2}
    # find_one called twice: pre-read + stale fetch
    mock_collection.find_one = AsyncMock(side_effect=[existing, existing])
    mock_collection.find_one_and_update = AsyncMock(return_value=None)

    with pytest.raises(StaleOutcomeError):
        await repo.upsert_decision(make_identifier(), make_cluster("c2"), [], t1)


# ── ensure_indexes: partial index R7 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_indexes_creates_partial_delta_index(repo, mock_collection):
    """R7: ensure_indexes creates idx_decision_store_delta with partialFilterExpression."""
    mock_collection.create_index = AsyncMock()

    await repo.ensure_indexes()

    # Collect all create_index calls
    calls = mock_collection.create_index.call_args_list
    partial_call = None
    for call in calls:
        kwargs = call.kwargs if call.kwargs else {}
        if kwargs.get("name") == "idx_decision_store_delta":
            partial_call = call
            break

    assert partial_call is not None, "idx_decision_store_delta index was not created"
    kwargs = partial_call.kwargs
    assert kwargs.get("partialFilterExpression") == {"updated_at": {"$exists": True}}, (
        "Partial index must filter on $exists; MongoDB rejects $ne in partialFilterExpression"
    )


# ── count_distinct_clusters ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_count_distinct_clusters_returns_count(repo, mock_collection):
    mock_collection.distinct = AsyncMock(return_value=["c1", "c2", "c3"])
    result = await repo.count_distinct_clusters()
    assert result == 3
    mock_collection.distinct.assert_called_once_with("current_placement.cluster_id")


@pytest.mark.asyncio
async def test_count_distinct_clusters_returns_zero_when_empty(repo, mock_collection):
    mock_collection.distinct = AsyncMock(return_value=[])
    result = await repo.count_distinct_clusters()
    assert result == 0


# ── average_cluster_size ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_average_cluster_size_returns_average(repo, mock_collection):
    agg_cursor = AsyncMock()
    agg_cursor.to_list = AsyncMock(return_value=[{"avg": 3.5}])
    mock_collection.aggregate = AsyncMock(return_value=agg_cursor)

    result = await repo.average_cluster_size()
    assert result == 3.5


@pytest.mark.asyncio
async def test_average_cluster_size_returns_zero_when_no_decisions(repo, mock_collection):
    agg_cursor = AsyncMock()
    agg_cursor.to_list = AsyncMock(return_value=[])
    mock_collection.aggregate = AsyncMock(return_value=agg_cursor)

    result = await repo.average_cluster_size()
    assert result == 0.0
