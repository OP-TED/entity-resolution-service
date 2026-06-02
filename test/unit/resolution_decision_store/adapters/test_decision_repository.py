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
    """Insert path: pre-read returns None → find_one_and_update returns the new doc."""
    now = datetime.now(UTC)
    mock_collection.find_one = AsyncMock(return_value=None)
    mock_collection.find_one_and_update = AsyncMock(return_value=make_doc(now))
    result = await repo.upsert_decision(make_identifier(), make_cluster(), [], now)
    assert isinstance(result, Decision)
    assert result.current_placement.cluster_id == "c1"


@pytest.mark.asyncio
async def test_upsert_sets_id_from_triad_hash(repo, mock_collection):
    """Insert path: returned doc has the expected triad hash as id."""
    now = datetime.now(UTC)
    expected_hash = derive_provisional_cluster_id(make_identifier())
    mock_collection.find_one = AsyncMock(return_value=None)
    mock_collection.find_one_and_update = AsyncMock(return_value=make_doc(now, triad_hash=expected_hash))
    result = await repo.upsert_decision(make_identifier(), make_cluster(), [], now)
    assert result.id == expected_hash


@pytest.mark.asyncio
async def test_upsert_skips_pre_read_when_existing_passed(repo, mock_collection):
    """Fast-path: when caller provides ``existing``, repository skips its own find_one."""
    now = datetime.now(UTC)
    existing = Decision(
        id=derive_provisional_cluster_id(make_identifier()),
        about_entity_mention=make_identifier(),
        current_placement=make_cluster(),
        candidates=[],
        created_at=now,
        updated_at=now,
    )
    mock_collection.find_one = AsyncMock()
    mock_collection.find_one_and_update = AsyncMock(return_value=make_doc(now))
    await repo.upsert_decision(make_identifier(), make_cluster("c2"), [], now, existing=existing)
    mock_collection.find_one.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_raises_stale_when_result_is_none(repo, mock_collection):
    """Update path: R2 stale filter rejects → find_one_and_update returns None → StaleOutcomeError.

    _fetch_existing_and_raise_stale is called which issues a single find_one.
    """
    now = datetime.now(UTC)
    older = now - timedelta(seconds=1)
    existing_doc = make_doc(now)
    existing_decision = Decision(
        id=existing_doc["_id"],
        about_entity_mention=make_identifier(),
        current_placement=make_cluster(),
        candidates=[],
        created_at=now,
        updated_at=now,
    )
    mock_collection.find_one_and_update = AsyncMock(return_value=None)
    mock_collection.find_one = AsyncMock(return_value=existing_doc)
    with pytest.raises(StaleOutcomeError):
        await repo.upsert_decision(make_identifier(), make_cluster(), [], older, existing=existing_decision)


@pytest.mark.asyncio
async def test_upsert_raises_operation_error_when_no_existing_doc(repo, mock_collection):
    """Insert path: find_one_and_update returns None (unexpected) + no doc found → RepositoryOperationError."""
    now = datetime.now(UTC)
    mock_collection.find_one_and_update = AsyncMock(return_value=None)
    mock_collection.find_one = AsyncMock(return_value=None)
    with pytest.raises(RepositoryOperationError):
        await repo.upsert_decision(make_identifier(), make_cluster(), [], now, existing=None)


@pytest.mark.asyncio
async def test_upsert_wraps_connection_failure(repo, mock_collection):
    """B3: ConnectionFailure on find_one_and_update → RepositoryConnectionError."""
    from pymongo.errors import ConnectionFailure
    mock_collection.find_one = AsyncMock(return_value=None)
    mock_collection.find_one_and_update = AsyncMock(side_effect=ConnectionFailure("down"))
    with pytest.raises(RepositoryConnectionError):
        await repo.upsert_decision(make_identifier(), make_cluster(), [], datetime.now(UTC))


@pytest.mark.asyncio
async def test_concurrent_inserts_one_wins(repo, mock_collection):
    """B2: Concurrent insert race — DuplicateKeyError caught, raises StaleOutcomeError.

    Two concurrent writers both see existing=None (from service pre-read before upsert).
    The slower writer receives DuplicateKeyError on the insert. We surface StaleOutcomeError
    — never silently drop the write or succeed with an incorrect result.
    """
    from pymongo.errors import DuplicateKeyError as MongoDuplicateKeyError
    now = datetime.now(UTC)
    existing = make_doc(now)
    mock_collection.find_one_and_update = AsyncMock(
        side_effect=MongoDuplicateKeyError("E11000 duplicate key error")
    )
    mock_collection.find_one = AsyncMock(return_value=existing)

    with pytest.raises(StaleOutcomeError):
        await repo.upsert_decision(make_identifier(), make_cluster(), [], now, existing=None)


@pytest.mark.asyncio
async def test_upsert_translates_pymongo_connection_failure_on_pre_read(repo, mock_collection):
    """B3: Raw pymongo ConnectionFailure on the internal pre-read → RepositoryConnectionError.

    When ``existing`` is not provided, the repository performs a pre-read via
    ``find_one``. That call must be wrapped in error translation so PyMongo
    exceptions never leak past the adapter boundary.
    """
    from pymongo.errors import ConnectionFailure
    mock_collection.find_one = AsyncMock(side_effect=ConnectionFailure("network error"))
    mock_collection.find_one_and_update = AsyncMock()

    with pytest.raises(RepositoryConnectionError):
        await repo.upsert_decision(make_identifier(), make_cluster(), [], datetime.now(UTC))

    mock_collection.find_one_and_update.assert_not_called()


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
    """Insert path: updated_at must NOT be in $set, created_at in $setOnInsert.

    On first insert (pre-read returns None), updated_at is intentionally absent
    per R1. The insert doc uses $setOnInsert only so updated_at is never written.
    """
    now = datetime.now(UTC)
    mock_collection.find_one = AsyncMock(return_value=None)
    mock_collection.find_one_and_update = AsyncMock(return_value=make_doc(now))

    await repo.upsert_decision(make_identifier(), make_cluster(), [], now)

    call_args = mock_collection.find_one_and_update.call_args
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
    """Update path (existing=Decision): updated_at MUST be set in $set (R1 placement change)."""
    now = datetime.now(UTC)
    existing_decision = Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster("c1"),
        candidates=[],
        created_at=now - timedelta(seconds=10),
        updated_at=None,
    )
    mock_collection.find_one_and_update = AsyncMock(return_value=make_doc(now))

    await repo.upsert_decision(make_identifier(), make_cluster("c2"), [], now, existing=existing_decision)

    call_args = mock_collection.find_one_and_update.call_args
    update_doc = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("update")
    assert update_doc is not None, "find_one_and_update was not called with an update doc"
    assert "updated_at" in update_doc.get("$set", {}), (
        "Update path must set updated_at in $set"
    )
    mock_collection.find_one.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_stale_filter_accepts_none_when_incoming_after_created_at(
    repo, mock_collection
):
    """R2: update path with R2 disjunction — succeeds when incoming > created_at (updated_at=None)."""
    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC)
    existing_decision = Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster("c1"),
        candidates=[],
        created_at=t1,
        updated_at=None,
    )
    mock_collection.find_one_and_update = AsyncMock(return_value=make_doc(t2))

    result = await repo.upsert_decision(make_identifier(), make_cluster("c2"), [], t2, existing=existing_decision)
    assert result is not None
    mock_collection.find_one.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_stale_filter_rejects_when_updated_at_none_and_incoming_older(
    repo, mock_collection
):
    """R2: update path returns None (stale, updated_at=None, incoming < created_at) → StaleOutcomeError."""
    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC)
    existing_decision = Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster("c1"),
        candidates=[],
        created_at=t2,
        updated_at=None,
    )
    existing_doc = {**make_doc(t2), "updated_at": None}
    mock_collection.find_one_and_update = AsyncMock(return_value=None)
    mock_collection.find_one = AsyncMock(return_value=existing_doc)

    with pytest.raises(StaleOutcomeError):
        await repo.upsert_decision(make_identifier(), make_cluster("c2"), [], t1, existing=existing_decision)


@pytest.mark.asyncio
async def test_upsert_stale_filter_rejects_regression(repo, mock_collection):
    """R2: update path returns None (stale, incoming < stored updated_at) → StaleOutcomeError."""
    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC)
    existing_decision = Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster("c1"),
        candidates=[],
        created_at=t1,
        updated_at=t2,
    )
    existing_doc = {**make_doc(t2), "updated_at": t2}
    mock_collection.find_one_and_update = AsyncMock(return_value=None)
    mock_collection.find_one = AsyncMock(return_value=existing_doc)

    with pytest.raises(StaleOutcomeError):
        await repo.upsert_decision(make_identifier(), make_cluster("c2"), [], t1, existing=existing_decision)


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


# ── increment_review_count ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_increment_review_count_issues_inc_operation(repo, mock_collection):
    """increment_review_count calls update_one with $inc: {previous_review_count: 1}."""
    mock_collection.update_one = AsyncMock()

    await repo.increment_review_count("decision-abc")

    mock_collection.update_one.assert_called_once_with(
        {"_id": "decision-abc"},
        {"$inc": {"previous_review_count": 1}},
    )


@pytest.mark.asyncio
async def test_increment_review_count_no_upsert(repo, mock_collection):
    """increment_review_count must NOT use upsert — missing doc is a no-op."""
    mock_collection.update_one = AsyncMock()

    await repo.increment_review_count("decision-xyz")

    call_kwargs = mock_collection.update_one.call_args.kwargs
    assert call_kwargs.get("upsert", False) is False


# ── find_with_filters: reviewed filter ───────────────────────────────────────


def _make_async_cursor(docs):
    """Build a mock cursor that yields docs asynchronously."""
    async def _gen():
        for doc in docs:
            yield doc

    cursor_mock = MagicMock()
    cursor_mock.sort.return_value = cursor_mock
    cursor_mock.limit.return_value = cursor_mock
    cursor_mock.__aiter__ = lambda self: _gen()
    return cursor_mock


@pytest.mark.asyncio
async def test_find_with_filters_reviewed_none_does_not_contain_lookup(repo, mock_collection):
    """reviewed=None: pipeline uses find(), NOT aggregate() — no $lookup against user_actions."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters

    mock_collection.find = MagicMock(return_value=_make_async_cursor([]))
    mock_collection.count_documents = AsyncMock(return_value=0)
    mock_collection.aggregate = AsyncMock()

    await repo.find_with_filters(
        filters=DecisionFilters(),
        cursor_params=CursorParams(cursor=None, limit=10),
        reviewed_since_placement=None,
    )

    mock_collection.aggregate.assert_not_called()
    mock_collection.find.assert_called_once()


@pytest.mark.asyncio
async def test_find_with_filters_reviewed_true_uses_lookup_and_matches_non_empty(repo, mock_collection):
    """reviewed=True: pipeline contains $lookup and $match for non-empty _has_recent_action."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters

    agg_cursor = AsyncMock()
    agg_cursor.__aiter__ = AsyncMock(return_value=iter([]))
    agg_cursor.to_list = AsyncMock(return_value=[])

    async def _aiter(self):
        return
        yield  # noqa: unreachable – makes this an async generator

    agg_cursor.__aiter__ = lambda self: _aiter(self)
    mock_collection.aggregate = MagicMock(return_value=agg_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)
    mock_collection.find = MagicMock()

    await repo.find_with_filters(
        filters=DecisionFilters(),
        cursor_params=CursorParams(cursor=None, limit=10),
        reviewed_since_placement=True,
    )

    mock_collection.aggregate.assert_called_once()
    pipeline = mock_collection.aggregate.call_args[0][0]

    stage_types = [list(s.keys())[0] for s in pipeline]
    assert "$lookup" in stage_types, "Pipeline must contain a $lookup stage"

    lookup_stage = next(s["$lookup"] for s in pipeline if "$lookup" in s)
    assert lookup_stage["from"] == "user_actions"
    assert lookup_stage["as"] == "_has_recent_action"
    assert "let" in lookup_stage
    assert "pipeline" in lookup_stage

    # The $match after lookup for reviewed=True must require non-empty array
    post_lookup_idx = stage_types.index("$lookup") + 1
    match_stages = [s for s in pipeline[post_lookup_idx:] if "$match" in s]
    assert match_stages, "Pipeline must have a $match after $lookup"
    match_expr = str(match_stages[0])
    assert "$ne" in match_expr or "ne" in match_expr, (
        "reviewed=True must match non-empty _has_recent_action"
    )


@pytest.mark.asyncio
async def test_find_with_filters_reviewed_false_uses_lookup_and_matches_empty(repo, mock_collection):
    """reviewed=False: pipeline contains $lookup and $match for empty _has_recent_action."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters

    async def _aiter(self):
        return
        yield

    agg_cursor = MagicMock()
    agg_cursor.__aiter__ = lambda self: _aiter(self)
    mock_collection.aggregate = MagicMock(return_value=agg_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)
    mock_collection.find = MagicMock()

    await repo.find_with_filters(
        filters=DecisionFilters(),
        cursor_params=CursorParams(cursor=None, limit=10),
        reviewed_since_placement=False,
    )

    mock_collection.aggregate.assert_called_once()
    pipeline = mock_collection.aggregate.call_args[0][0]

    stage_types = [list(s.keys())[0] for s in pipeline]
    assert "$lookup" in stage_types

    post_lookup_idx = stage_types.index("$lookup") + 1
    match_stages = [s for s in pipeline[post_lookup_idx:] if "$match" in s]
    assert match_stages, "Pipeline must have a $match after $lookup"
    match_expr = str(match_stages[0])
    assert "$eq" in match_expr or "eq" in match_expr, (
        "reviewed=False must match empty _has_recent_action"
    )


@pytest.mark.asyncio
async def test_find_with_filters_reviewed_pipeline_excludes_has_recent_action_field(repo, mock_collection):
    """Pipeline must project out _has_recent_action so it is not returned in results."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters

    async def _aiter(self):
        return
        yield

    agg_cursor = MagicMock()
    agg_cursor.__aiter__ = lambda self: _aiter(self)
    mock_collection.aggregate = MagicMock(return_value=agg_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)

    await repo.find_with_filters(
        filters=DecisionFilters(),
        cursor_params=CursorParams(cursor=None, limit=10),
        reviewed_since_placement=True,
    )

    pipeline = mock_collection.aggregate.call_args[0][0]
    project_stages = [s for s in pipeline if "$project" in s]
    assert project_stages, "Pipeline must contain a $project stage to remove _has_recent_action"
    # The field must be excluded (value 0 or absent from projection)
    project = project_stages[-1]["$project"]
    assert project.get("_has_recent_action", 1) == 0, (
        "$project must exclude _has_recent_action"
    )


@pytest.mark.asyncio
async def test_review_filter_applies_match_before_limit(repo, mock_collection):
    """D2 regression: the review $match must precede $sort/$limit (no page under-fill)."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters

    async def _aiter(self):
        return
        yield

    agg_cursor = MagicMock()
    agg_cursor.__aiter__ = lambda self: _aiter(self)
    mock_collection.aggregate = MagicMock(return_value=agg_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)

    await repo.find_with_filters(
        filters=DecisionFilters(),
        cursor_params=CursorParams(cursor=None, limit=10),
        reviewed_since_placement=True,
    )

    pipeline = mock_collection.aggregate.call_args[0][0]
    stage_types = [list(s.keys())[0] for s in pipeline]
    lookup_idx = stage_types.index("$lookup")
    # The review $match is the first $match after the $lookup.
    review_match_idx = next(
        i for i, s in enumerate(pipeline) if i > lookup_idx and "$match" in s
    )
    limit_idx = stage_types.index("$limit")
    assert review_match_idx < limit_idx, (
        "Review $match must run before $limit, otherwise pagination under-fills"
    )


@pytest.mark.asyncio
async def test_ever_reviewed_filter_adds_previous_review_count_match(repo, mock_collection):
    """ever_reviewed=True adds a plain previous_review_count > 0 match (no extra $lookup)."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters

    captured: dict = {}

    def _find(query, *args, **kwargs):
        captured["query"] = query
        return _make_async_cursor([])

    mock_collection.find = MagicMock(side_effect=_find)
    mock_collection.count_documents = AsyncMock(return_value=0)
    mock_collection.aggregate = AsyncMock()

    await repo.find_with_filters(
        filters=DecisionFilters(),
        cursor_params=CursorParams(cursor=None, limit=10),
        ever_reviewed=True,
    )

    mock_collection.aggregate.assert_not_called()  # counter match needs no aggregation
    assert captured["query"].get("previous_review_count") == {"$gt": 0}


@pytest.mark.asyncio
async def test_ever_reviewed_false_matches_never_reviewed(repo, mock_collection):
    """ever_reviewed=False matches a missing/None/0 counter via $in (no $not, engine-safe)."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters

    captured: dict = {}

    def _find(query, *args, **kwargs):
        captured["query"] = query
        return _make_async_cursor([])

    mock_collection.find = MagicMock(side_effect=_find)
    mock_collection.count_documents = AsyncMock(return_value=0)
    mock_collection.aggregate = AsyncMock()

    await repo.find_with_filters(
        filters=DecisionFilters(),
        cursor_params=CursorParams(cursor=None, limit=10),
        ever_reviewed=False,
    )

    mock_collection.aggregate.assert_not_called()
    assert captured["query"].get("previous_review_count") == {"$in": [0, None]}


@pytest.mark.asyncio
async def test_review_filters_combine_counter_match_into_aggregation(repo, mock_collection):
    """ever_reviewed + reviewed_since_placement together: the counter $match survives
    into the aggregation that applies the user_actions review filter."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters

    async def _aiter(self):
        return
        yield

    agg_cursor = MagicMock()
    agg_cursor.__aiter__ = lambda self: _aiter(self)
    mock_collection.aggregate = MagicMock(return_value=agg_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)

    await repo.find_with_filters(
        filters=DecisionFilters(),
        cursor_params=CursorParams(cursor=None, limit=10),
        ever_reviewed=True,
        reviewed_since_placement=False,
    )

    pipeline = mock_collection.aggregate.call_args[0][0]
    first_match = next(s["$match"] for s in pipeline if "$match" in s)
    assert first_match.get("previous_review_count") == {"$gt": 0}, (
        "the ever_reviewed counter predicate must carry into the aggregation $match"
    )


@pytest.mark.asyncio
async def test_find_reviewed_since_placement_maps_matches(repo, mock_collection):
    """Returns True only for decisions whose triad has a user_action since placement."""
    now = datetime.now(UTC)
    reviewed = Decision(
        id="hash-reviewed",
        about_entity_mention=make_identifier(source_id="s1", request_id="r1"),
        current_placement=make_cluster(),
        candidates=[],
        created_at=now,
        updated_at=None,
    )
    pending = Decision(
        id="hash-pending",
        about_entity_mention=make_identifier(source_id="s2", request_id="r2"),
        current_placement=make_cluster(),
        candidates=[],
        created_at=now,
        updated_at=None,
    )

    # user_actions returns a recent action only for the reviewed decision's triad.
    ua_collection = MagicMock()
    ua_collection.find = MagicMock(
        return_value=_make_async_cursor(
            [{"about_entity_mention": {"source_id": "s1", "request_id": "r1",
                                       "entity_type": "Person"}}]
        )
    )
    database = MagicMock()
    database.__getitem__ = MagicMock(return_value=ua_collection)
    mock_collection.database = database

    result = await repo.find_reviewed_since_placement([reviewed, pending])

    assert result == {"hash-reviewed": True, "hash-pending": False}
    # Single batched query, restricted to user_actions.
    database.__getitem__.assert_called_once_with("user_actions")
    ua_query = ua_collection.find.call_args[0][0]
    assert "$or" in ua_query and len(ua_query["$or"]) == 2


@pytest.mark.asyncio
async def test_find_reviewed_since_placement_empty_input(repo):
    """Empty input returns an empty mapping without querying."""
    assert await repo.find_reviewed_since_placement([]) == {}


@pytest.mark.asyncio
async def test_find_with_filters_unfiltered_bulk_sync_reviewed_none_unchanged(repo, mock_collection):
    """Bulk-sync caller (filters=None, no reviewed kwarg) must use find(), not aggregate()."""
    mock_collection.find = MagicMock(return_value=_make_async_cursor([]))
    mock_collection.aggregate = AsyncMock()

    # Simulate the bulk-sync call pattern: no reviewed kwarg at all
    await repo.find_with_filters(filters=None, cursor_params=CursorParams(cursor=None, limit=10))

    mock_collection.aggregate.assert_not_called()
    mock_collection.find.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_does_not_overwrite_previous_review_count(repo, mock_collection):
    """Integration write ($set / $setOnInsert) must NOT include previous_review_count.

    If previous_review_count appears in $set, ERE re-integration would reset
    the counter. This test verifies the built update docs stay clean.
    """
    now = datetime.now(UTC)
    identifier = make_identifier()
    current = make_cluster()

    # Insert path
    insert_doc = repo._build_insert_doc(identifier, current, [], now)
    assert "previous_review_count" not in insert_doc.get("$setOnInsert", {}), (
        "Insert doc must not touch previous_review_count"
    )

    # Update path
    update_doc = repo._build_update_doc(identifier, current, [], now)
    assert "previous_review_count" not in update_doc.get("$set", {}), (
        "Update doc must not touch previous_review_count"
    )


# ── find_with_filters: cluster-size sort ─────────────────────────────────────


@pytest.mark.asyncio
async def test_find_with_filters_cluster_size_asc_uses_aggregation(repo, mock_collection):
    """cluster_size ordering must use aggregation (find() cannot sort on a derived field)."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters, DecisionOrdering

    async def _aiter(self):
        return
        yield

    agg_cursor = MagicMock()
    agg_cursor.__aiter__ = lambda self: _aiter(self)
    mock_collection.aggregate = MagicMock(return_value=agg_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)
    mock_collection.find = MagicMock()

    await repo.find_with_filters(
        filters=DecisionFilters(ordering=DecisionOrdering.CLUSTER_SIZE_ASC),
        cursor_params=CursorParams(cursor=None, limit=10),
    )

    mock_collection.aggregate.assert_called_once()
    mock_collection.find.assert_not_called()


@pytest.mark.asyncio
async def test_find_with_filters_cluster_size_desc_uses_aggregation(repo, mock_collection):
    """cluster_size descending also routes through aggregation."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters, DecisionOrdering

    async def _aiter(self):
        return
        yield

    agg_cursor = MagicMock()
    agg_cursor.__aiter__ = lambda self: _aiter(self)
    mock_collection.aggregate = MagicMock(return_value=agg_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)
    mock_collection.find = MagicMock()

    await repo.find_with_filters(
        filters=DecisionFilters(ordering=DecisionOrdering.CLUSTER_SIZE_DESC),
        cursor_params=CursorParams(cursor=None, limit=10),
    )

    mock_collection.aggregate.assert_called_once()
    mock_collection.find.assert_not_called()


@pytest.mark.asyncio
async def test_find_with_filters_cluster_size_pipeline_contains_lookup(repo, mock_collection):
    """Pipeline for cluster_size sort must contain a $lookup against cluster_sizes."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters, DecisionOrdering

    async def _aiter(self):
        return
        yield

    agg_cursor = MagicMock()
    agg_cursor.__aiter__ = lambda self: _aiter(self)
    mock_collection.aggregate = MagicMock(return_value=agg_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)

    await repo.find_with_filters(
        filters=DecisionFilters(ordering=DecisionOrdering.CLUSTER_SIZE_ASC),
        cursor_params=CursorParams(cursor=None, limit=10),
    )

    pipeline = mock_collection.aggregate.call_args[0][0]
    stage_types = [list(s.keys())[0] for s in pipeline]
    assert "$lookup" in stage_types, "Cluster-size pipeline must contain $lookup"

    lookup = next(s["$lookup"] for s in pipeline if "$lookup" in s)
    assert lookup["from"] == "cluster_sizes", "$lookup must target cluster_sizes collection"
    assert lookup["localField"] == "current_placement.cluster_id"
    assert lookup["foreignField"] == "_id"
    assert lookup["as"] == "_cluster_meta"


@pytest.mark.asyncio
async def test_find_with_filters_cluster_size_pipeline_adds_cluster_size_field(repo, mock_collection):
    """Pipeline must $addFields cluster_size from the joined _cluster_meta array."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters, DecisionOrdering

    async def _aiter(self):
        return
        yield

    agg_cursor = MagicMock()
    agg_cursor.__aiter__ = lambda self: _aiter(self)
    mock_collection.aggregate = MagicMock(return_value=agg_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)

    await repo.find_with_filters(
        filters=DecisionFilters(ordering=DecisionOrdering.CLUSTER_SIZE_DESC),
        cursor_params=CursorParams(cursor=None, limit=10),
    )

    pipeline = mock_collection.aggregate.call_args[0][0]
    add_fields = [s.get("$addFields") for s in pipeline if "$addFields" in s]
    assert add_fields, "Pipeline must contain an $addFields stage"
    assert any("cluster_size" in f for f in add_fields), (
        "$addFields must define cluster_size"
    )


@pytest.mark.asyncio
async def test_find_with_filters_cluster_size_pipeline_projects_out_meta(repo, mock_collection):
    """Pipeline must $project _cluster_meta out so _from_document receives clean docs."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters, DecisionOrdering

    async def _aiter(self):
        return
        yield

    agg_cursor = MagicMock()
    agg_cursor.__aiter__ = lambda self: _aiter(self)
    mock_collection.aggregate = MagicMock(return_value=agg_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)

    await repo.find_with_filters(
        filters=DecisionFilters(ordering=DecisionOrdering.CLUSTER_SIZE_ASC),
        cursor_params=CursorParams(cursor=None, limit=10),
    )

    pipeline = mock_collection.aggregate.call_args[0][0]
    project_stages = [s["$project"] for s in pipeline if "$project" in s]
    assert project_stages, "Pipeline must contain $project"
    # _cluster_meta must be removed (value 0)
    assert any(p.get("_cluster_meta", 1) == 0 for p in project_stages), (
        "$project must exclude _cluster_meta"
    )


@pytest.mark.asyncio
async def test_find_with_filters_cluster_size_pipeline_match_before_lookup(repo, mock_collection):
    """$match (filters) must appear before $lookup so Mongo can use indexes."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters, DecisionOrdering

    async def _aiter(self):
        return
        yield

    agg_cursor = MagicMock()
    agg_cursor.__aiter__ = lambda self: _aiter(self)
    mock_collection.aggregate = MagicMock(return_value=agg_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)

    await repo.find_with_filters(
        filters=DecisionFilters(ordering=DecisionOrdering.CLUSTER_SIZE_ASC),
        cursor_params=CursorParams(cursor=None, limit=10),
    )

    pipeline = mock_collection.aggregate.call_args[0][0]
    stage_types = [list(s.keys())[0] for s in pipeline]
    match_idx = stage_types.index("$match")
    lookup_idx = stage_types.index("$lookup")
    assert match_idx < lookup_idx, "$match must appear before $lookup"


@pytest.mark.asyncio
async def test_find_with_filters_cluster_size_sort_uses_cluster_size_and_id(repo, mock_collection):
    """$sort must sort by cluster_size (asc) + _id (asc) for ascending ordering."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters, DecisionOrdering

    async def _aiter(self):
        return
        yield

    agg_cursor = MagicMock()
    agg_cursor.__aiter__ = lambda self: _aiter(self)
    mock_collection.aggregate = MagicMock(return_value=agg_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)

    await repo.find_with_filters(
        filters=DecisionFilters(ordering=DecisionOrdering.CLUSTER_SIZE_ASC),
        cursor_params=CursorParams(cursor=None, limit=10),
    )

    pipeline = mock_collection.aggregate.call_args[0][0]
    sort_stages = [s["$sort"] for s in pipeline if "$sort" in s]
    assert sort_stages, "Pipeline must contain $sort"
    sort = sort_stages[-1]  # the final sort stage
    assert sort.get("cluster_size") == 1, "Ascending: cluster_size direction must be 1"
    assert sort.get("_id") == 1, "Ascending: _id tiebreaker direction must match"


@pytest.mark.asyncio
async def test_find_with_filters_cluster_size_desc_sort_direction(repo, mock_collection):
    """$sort for descending cluster_size must have cluster_size: -1, _id: -1."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters, DecisionOrdering

    async def _aiter(self):
        return
        yield

    agg_cursor = MagicMock()
    agg_cursor.__aiter__ = lambda self: _aiter(self)
    mock_collection.aggregate = MagicMock(return_value=agg_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)

    await repo.find_with_filters(
        filters=DecisionFilters(ordering=DecisionOrdering.CLUSTER_SIZE_DESC),
        cursor_params=CursorParams(cursor=None, limit=10),
    )

    pipeline = mock_collection.aggregate.call_args[0][0]
    sort_stages = [s["$sort"] for s in pipeline if "$sort" in s]
    assert sort_stages
    sort = sort_stages[-1]
    assert sort.get("cluster_size") == -1, "Descending: cluster_size direction must be -1"
    assert sort.get("_id") == -1, "Descending: _id tiebreaker direction must match"


@pytest.mark.asyncio
async def test_find_with_filters_legacy_orderings_still_use_find(repo, mock_collection):
    """Legacy orderings (confidence_score, created_at, updated_at) must NOT use aggregate()."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters, DecisionOrdering

    for ordering in [
        DecisionOrdering.CONFIDENCE_ASC,
        DecisionOrdering.CONFIDENCE_DESC,
        DecisionOrdering.CREATED_AT_ASC,
        DecisionOrdering.CREATED_AT_DESC,
        DecisionOrdering.UPDATED_AT_ASC,
        DecisionOrdering.UPDATED_AT_DESC,
    ]:
        mock_collection.aggregate = AsyncMock()
        mock_collection.count_documents = AsyncMock(return_value=0)
        mock_collection.find = MagicMock(return_value=_make_async_cursor([]))

        await repo.find_with_filters(
            filters=DecisionFilters(ordering=ordering),
            cursor_params=CursorParams(cursor=None, limit=10),
        )

        mock_collection.aggregate.assert_not_called(), (
            f"Legacy ordering {ordering!r} must not trigger aggregation"
        )


@pytest.mark.asyncio
async def test_find_with_filters_cluster_size_with_reviewed_filter_includes_both_lookups(
    repo, mock_collection
):
    """cluster_size + reviewed=True: pipeline must contain two $lookup stages."""
    from ers.commons.domain.data_transfer_objects import DecisionFilters, DecisionOrdering

    async def _aiter(self):
        return
        yield

    agg_cursor = MagicMock()
    agg_cursor.__aiter__ = lambda self: _aiter(self)
    mock_collection.aggregate = MagicMock(return_value=agg_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)

    await repo.find_with_filters(
        filters=DecisionFilters(ordering=DecisionOrdering.CLUSTER_SIZE_DESC),
        cursor_params=CursorParams(cursor=None, limit=10),
        reviewed_since_placement=True,
    )

    pipeline = mock_collection.aggregate.call_args[0][0]
    lookup_stages = [s["$lookup"] for s in pipeline if "$lookup" in s]
    assert len(lookup_stages) == 2, (
        "cluster_size + reviewed pipeline must contain two $lookup stages"
    )
    sources = {s["from"] for s in lookup_stages}
    assert "cluster_sizes" in sources
    assert "user_actions" in sources
