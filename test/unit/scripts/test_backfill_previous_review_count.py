"""Unit tests for scripts.backfill_previous_review_count."""
from datetime import UTC, datetime
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


_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count_actions_per_decision_derives_correct_id():
    """A well-formed triad is mapped to its derive_provisional_cluster_id with (count, max_action_at)."""
    triad = {"source_id": "s1", "request_id": "r1", "entity_type": "Person"}
    rows = [{"_id": triad, "count": 4, "max_action_at": _T0}]
    db = _make_db(aggregate_rows=rows)

    result = await _count_actions_per_decision(db)

    identifier = EntityMentionIdentifier(source_id="s1", request_id="r1", entity_type="Person")
    expected_id = derive_provisional_cluster_id(identifier)
    assert result == {expected_id: (4, _T0)}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count_actions_per_decision_skips_malformed_triad():
    """A plain string _id (not a dict) is skipped and the result is empty."""
    rows = [{"_id": "not-a-dict", "count": 2, "max_action_at": _T0}]
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
    """Each decision produces an UpdateOne aggregation-pipeline op with both review fields, upsert=False."""
    counts = {"decision_abc": (5, _T0), "decision_xyz": (2, _T0)}

    ops = await _build_bulk_ops(counts)

    assert len(ops) == 2
    for op in ops:
        assert isinstance(op, UpdateOne)
        assert op._upsert is False
        # Aggregation-update pipeline is stored as a list; first stage is $set.
        assert isinstance(op._doc, list)
        set_stage = op._doc[0]["$set"]
        assert "previous_review_count" in set_stage
        assert "reviewed_since_placement" in set_stage

    values = {op._filter["_id"]: op._doc[0]["$set"]["previous_review_count"] for op in ops}
    assert values == {"decision_abc": 5, "decision_xyz": 2}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_bulk_ops_reviewed_since_placement_uses_boundary_cond():
    """reviewed_since_placement is a $cond comparing max_action_at against the placement boundary."""
    counts = {"decision_abc": (1, _T0)}

    ops = await _build_bulk_ops(counts)

    cond_expr = ops[0]._doc[0]["$set"]["reviewed_since_placement"]
    assert "$cond" in cond_expr
    gt_expr = cond_expr["$cond"][0]
    assert "$gt" in gt_expr
    # max_action_at literal is the first operand
    assert gt_expr["$gt"][0] == _T0
    # placement boundary is ifNull(updated_at, created_at)
    boundary = gt_expr["$gt"][1]
    assert boundary == {"$ifNull": ["$updated_at", "$created_at"]}


# ── _run_backfill ──────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_backfill_dry_run_makes_no_writes():
    """In dry-run mode bulk_write is never called."""
    triad = {"source_id": "s1", "request_id": "r1", "entity_type": "Person"}
    rows = [{"_id": triad, "count": 3, "max_action_at": _T0}]
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
