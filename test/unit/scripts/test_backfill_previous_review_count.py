"""Unit tests for scripts.backfill_previous_review_count."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from erspec.models.core import EntityMentionIdentifier
from pymongo import UpdateOne

from ers.commons.adapters.provisional_id import derive_provisional_cluster_id
from scripts.backfill_previous_review_count import (
    _build_bulk_ops,
    _count_actions_per_decision,
    _run_backfill,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_async_cursor(rows: list) -> AsyncMock:
    cursor = AsyncMock()
    cursor.to_list = AsyncMock(return_value=rows)
    return cursor


def _make_db(aggregate_rows: list, bulk_write_result=None) -> MagicMock:
    """Build a mock AsyncDatabase with user_actions and decisions collections."""
    if bulk_write_result is None:
        bw_result = MagicMock()
        bw_result.modified_count = 0
        bulk_write_result = bw_result

    user_actions_col = MagicMock()
    user_actions_col.aggregate = AsyncMock(return_value=_make_async_cursor(aggregate_rows))

    decisions_col = AsyncMock()
    decisions_col.bulk_write = AsyncMock(return_value=bulk_write_result)

    db = MagicMock()

    def _getitem(name):
        if name == "user_actions":
            return user_actions_col
        if name == "decisions":
            return decisions_col
        raise KeyError(name)

    db.__getitem__ = MagicMock(side_effect=_getitem)
    return db


# ── _count_actions_per_decision ────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count_actions_per_decision_derives_correct_id():
    """A well-formed triad is mapped to its derive_provisional_cluster_id with count."""
    triad = {"source_id": "s1", "request_id": "r1", "entity_type": "Person"}
    rows = [{"_id": triad, "count": 4}]
    db = _make_db(aggregate_rows=rows)

    result = await _count_actions_per_decision(db)

    identifier = EntityMentionIdentifier(source_id="s1", request_id="r1", entity_type="Person")
    expected_id = derive_provisional_cluster_id(identifier)
    assert result == {expected_id: 4}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count_actions_per_decision_skips_malformed_triad():
    """A plain string _id (not a dict) is skipped and the result is empty."""
    rows = [{"_id": "not-a-dict", "count": 2}]
    db = _make_db(aggregate_rows=rows)

    result = await _count_actions_per_decision(db)

    assert result == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count_actions_per_decision_empty_returns_empty():
    """Empty aggregate returns an empty dict."""
    db = _make_db(aggregate_rows=[])

    result = await _count_actions_per_decision(db)

    assert result == {}


# ── _build_bulk_ops ────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_bulk_ops_creates_update_for_each_decision():
    """Each decision_id produces an UpdateOne with $set.previous_review_count, upsert=False."""
    counts = {"decision_abc": 5, "decision_xyz": 2}

    ops = await _build_bulk_ops(counts)

    assert len(ops) == 2
    for op in ops:
        assert isinstance(op, UpdateOne)
        assert "previous_review_count" in op._doc["$set"]
        assert op._upsert is False

    values = {
        op._filter["_id"]: op._doc["$set"]["previous_review_count"]
        for op in ops
    }
    assert values == {"decision_abc": 5, "decision_xyz": 2}


# ── _run_backfill ──────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_backfill_dry_run_makes_no_writes():
    """In dry-run mode bulk_write is never called."""
    triad = {"source_id": "s1", "request_id": "r1", "entity_type": "Person"}
    rows = [{"_id": triad, "count": 3}]
    db = _make_db(aggregate_rows=rows)
    decisions_col = db["decisions"]

    await _run_backfill(db, dry_run=True, batch_size=500)

    decisions_col.bulk_write.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_backfill_empty_user_actions_makes_no_writes():
    """When there are no user actions, bulk_write is never called."""
    db = _make_db(aggregate_rows=[])
    decisions_col = db["decisions"]

    await _run_backfill(db, dry_run=False, batch_size=500)

    decisions_col.bulk_write.assert_not_called()
