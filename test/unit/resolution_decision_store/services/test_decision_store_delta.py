"""Unit tests for DecisionStoreService.query_decisions_delta.

R3: query_decisions_delta routes to find_delta_for_source (not find_with_filters).
Cold-start (updated_since=None) returns only decisions where updated_at is non-null.
"""
from datetime import UTC, datetime
from unittest.mock import MagicMock, create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers import config
from ers.commons.domain.data_transfer_objects import CursorPage
from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository
from ers.resolution_decision_store.domain.errors import RepositoryConnectionError
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

UTC = UTC


def make_decision(source_id: str = "SRC_A") -> Decision:
    now = datetime.now(UTC)
    identifier = EntityMentionIdentifier(
        source_id=source_id, request_id="req1", entity_type="Person"
    )
    cluster = ClusterReference(cluster_id="c1", confidence_score=0.9, similarity_score=0.85)
    return Decision(
        id="hash123",
        about_entity_mention=identifier,
        current_placement=cluster,
        candidates=[],
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def mock_repo():
    return create_autospec(MongoDecisionRepository, instance=True)


# ── module-level tests using find_delta_for_source ────────────────────────────


@pytest.mark.asyncio
async def test_delta_with_snapshot(mock_repo):
    """R3: warm path passes source_id and updated_since to find_delta_for_source."""
    svc = DecisionStoreService(repository=mock_repo)
    t0 = datetime(2026, 3, 12, 10, 0, 0, tzinfo=UTC)
    mock_repo.find_delta_for_source.return_value = CursorPage(results=[], next_cursor=None)

    await svc.query_decisions_delta(source_id="SRC_A", updated_since=t0)

    mock_repo.find_delta_for_source.assert_awaited_once()
    call_kwargs = mock_repo.find_delta_for_source.call_args.kwargs
    assert call_kwargs["source_id"] == "SRC_A"
    assert call_kwargs["updated_since"] == t0


@pytest.mark.asyncio
async def test_delta_without_snapshot(mock_repo):
    """R3: cold-start passes updated_since=None to find_delta_for_source."""
    svc = DecisionStoreService(repository=mock_repo)
    mock_repo.find_delta_for_source.return_value = CursorPage(results=[], next_cursor=None)

    await svc.query_decisions_delta(source_id="SRC_B", updated_since=None)

    call_kwargs = mock_repo.find_delta_for_source.call_args.kwargs
    assert call_kwargs["source_id"] == "SRC_B"
    assert call_kwargs["updated_since"] is None


@pytest.mark.asyncio
async def test_delta_returns_page(mock_repo):
    """R3: service returns the page from find_delta_for_source unchanged."""
    svc = DecisionStoreService(repository=mock_repo)
    decisions = [make_decision() for _ in range(3)]
    expected_page = CursorPage(results=decisions, next_cursor="tok")
    mock_repo.find_delta_for_source.return_value = expected_page

    result = await svc.query_decisions_delta(source_id="SRC_A", updated_since=None)

    assert result is expected_page


@pytest.mark.asyncio
async def test_delta_returns_empty_page(mock_repo):
    """R3: empty page is passed through unchanged."""
    svc = DecisionStoreService(repository=mock_repo)
    empty_page = CursorPage(results=[], next_cursor=None)
    mock_repo.find_delta_for_source.return_value = empty_page

    result = await svc.query_decisions_delta(source_id="SRC_A", updated_since=None)

    assert result is empty_page
    assert result.results == []
    assert result.next_cursor is None


@pytest.mark.asyncio
async def test_delta_respects_page_size_cap(mock_repo):
    """R3: page_size is capped at DECISION_STORE_MAX_PAGE_SIZE."""
    svc = DecisionStoreService(repository=mock_repo)
    mock_repo.find_delta_for_source.return_value = CursorPage(results=[], next_cursor=None)

    await svc.query_decisions_delta(
        source_id="SRC_A", updated_since=None, page_size=99999
    )

    call_kwargs = mock_repo.find_delta_for_source.call_args.kwargs
    assert call_kwargs["cursor_params"].limit == config.DECISION_STORE_MAX_PAGE_SIZE


@pytest.mark.asyncio
async def test_delta_uses_default_page_size(mock_repo):
    """R3: when page_size is None, uses DECISION_STORE_DEFAULT_PAGE_SIZE."""
    svc = DecisionStoreService(repository=mock_repo)
    mock_repo.find_delta_for_source.return_value = CursorPage(results=[], next_cursor=None)

    await svc.query_decisions_delta(source_id="SRC_A", updated_since=None)

    call_kwargs = mock_repo.find_delta_for_source.call_args.kwargs
    assert call_kwargs["cursor_params"].limit == config.DECISION_STORE_DEFAULT_PAGE_SIZE


@pytest.mark.asyncio
async def test_delta_passes_cursor(mock_repo):
    """R3: cursor token is forwarded to find_delta_for_source."""
    svc = DecisionStoreService(repository=mock_repo)
    mock_repo.find_delta_for_source.return_value = CursorPage(results=[], next_cursor=None)

    await svc.query_decisions_delta(
        source_id="SRC_A", updated_since=None, cursor="opaque-token"
    )

    call_kwargs = mock_repo.find_delta_for_source.call_args.kwargs
    assert call_kwargs["cursor_params"].cursor == "opaque-token"


@pytest.mark.asyncio
async def test_delta_propagates_connection_error(mock_repo):
    """R3: RepositoryConnectionError from find_delta_for_source propagates."""
    svc = DecisionStoreService(repository=mock_repo)
    mock_repo.find_delta_for_source.side_effect = RepositoryConnectionError("MongoDB down")

    with pytest.raises(RepositoryConnectionError):
        await svc.query_decisions_delta(source_id="SRC_A", updated_since=None)


# ── cold-start filter unit tests (repository level) ───────────────────────────


def _make_cursor_mock(docs):
    """Return a MagicMock that behaves like an async pymongo cursor."""
    async def _gen():
        for doc in docs:
            yield doc

    cursor_mock = MagicMock()
    cursor_mock.sort.return_value = cursor_mock
    cursor_mock.limit.return_value = cursor_mock
    cursor_mock.__aiter__ = lambda self: _gen()
    return cursor_mock


@pytest.mark.asyncio
async def test_cold_start_filter_uses_exists_true(mock_repo):
    """U-07: cold-start (updated_since=None) filters updated_at to $exists: True only.

    DocumentDB compatibility — ``$exists: True`` alone is sufficient because
    the insert path omits ``updated_at`` entirely (R1). The query then aligns
    exactly with the partial index ``partialFilterExpression`` so any planner
    can use the index, and we avoid the ``$ne`` operator (DocumentDB does not
    use indexes well for ``$ne``).
    """
    from unittest.mock import MagicMock

    from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository

    mock_collection = MagicMock()
    mock_collection.find = MagicMock(return_value=_make_cursor_mock([]))
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)

    repo = MongoDecisionRepository(mock_db)
    await repo.find_delta_for_source(source_id="S", updated_since=None)

    call_args = mock_collection.find.call_args
    query = call_args.args[0] if call_args.args else call_args.kwargs.get("filter", {})
    updated_at_filter = query.get("updated_at", {})
    assert updated_at_filter == {"$exists": True}, (
        "Cold-start filter must be exactly {$exists: True} (no $ne, no nesting)"
    )


@pytest.mark.asyncio
async def test_warm_filter_uses_gt(mock_repo):
    """U-08: warm path (updated_since=T) filters updated_at to $gt: T."""
    from unittest.mock import MagicMock

    from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository

    t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    mock_collection = MagicMock()
    mock_collection.find = MagicMock(return_value=_make_cursor_mock([]))
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)

    repo = MongoDecisionRepository(mock_db)
    await repo.find_delta_for_source(source_id="S", updated_since=t0)

    call_args = mock_collection.find.call_args
    query = call_args.args[0] if call_args.args else call_args.kwargs.get("filter", {})
    updated_at_filter = query.get("updated_at", {})
    assert updated_at_filter.get("$gt") == t0, (
        "Warm filter must use $gt: T on updated_at"
    )


class TestQueryDecisionsDelta:
    """Legacy class-based tests — skipped by pytest-asyncio auto mode; kept for reference."""
