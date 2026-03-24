"""Unit tests for MongoDecisionCurationRepository (mocked MongoDB collection)."""
from datetime import datetime, timezone, timedelta
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
    now = datetime.now(timezone.utc)
    mock_collection.find_one_and_update = AsyncMock(return_value=make_doc(now))
    result = await repo.upsert_decision(make_identifier(), make_cluster(), [], now)
    assert isinstance(result, Decision)
    assert result.current_placement.cluster_id == "c1"


@pytest.mark.asyncio
async def test_upsert_sets_id_from_triad_hash(repo, mock_collection):
    now = datetime.now(timezone.utc)
    expected_hash = derive_provisional_cluster_id(make_identifier())
    mock_collection.find_one_and_update = AsyncMock(return_value=make_doc(now, triad_hash=expected_hash))
    result = await repo.upsert_decision(make_identifier(), make_cluster(), [], now)
    assert result.id == expected_hash


@pytest.mark.asyncio
async def test_upsert_raises_stale_when_result_is_none(repo, mock_collection):
    now = datetime.now(timezone.utc)
    older = now - timedelta(seconds=1)
    mock_collection.find_one_and_update = AsyncMock(return_value=None)
    mock_collection.find_one = AsyncMock(return_value=make_doc(now))
    with pytest.raises(StaleOutcomeError):
        await repo.upsert_decision(make_identifier(), make_cluster(), [], older)


@pytest.mark.asyncio
async def test_upsert_raises_operation_error_when_no_existing_doc(repo, mock_collection):
    now = datetime.now(timezone.utc)
    mock_collection.find_one_and_update = AsyncMock(return_value=None)
    mock_collection.find_one = AsyncMock(return_value=None)
    with pytest.raises(RepositoryOperationError):
        await repo.upsert_decision(make_identifier(), make_cluster(), [], now)


@pytest.mark.asyncio
async def test_upsert_wraps_connection_failure(repo, mock_collection):
    from pymongo.errors import ConnectionFailure
    mock_collection.find_one_and_update = AsyncMock(side_effect=ConnectionFailure("down"))
    with pytest.raises(RepositoryConnectionError):
        await repo.upsert_decision(make_identifier(), make_cluster(), [], datetime.now(timezone.utc))


# ── find_by_triad ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_by_triad_returns_decision_when_found(repo, mock_collection):
    now = datetime.now(timezone.utc)
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
    now = datetime.now(timezone.utc)
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
    now = datetime.now(timezone.utc)
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
