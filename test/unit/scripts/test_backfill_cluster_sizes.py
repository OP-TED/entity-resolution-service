"""Unit tests for scripts.backfill_cluster_sizes."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo import UpdateOne

from scripts.backfill_cluster_sizes import (
    _aggregate_cluster_counts,
    _build_upsert_ops,
    _run_backfill,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_async_cursor(rows: list) -> AsyncMock:
    """Return an AsyncMock cursor whose .to_list() resolves to rows."""
    cursor = AsyncMock()
    cursor.to_list = AsyncMock(return_value=rows)
    return cursor


def _make_bulk_write_result(upserted: int = 0, modified: int = 0) -> MagicMock:
    result = MagicMock()
    result.upserted_count = upserted
    result.modified_count = modified
    return result


def _make_db(aggregate_rows: list, bulk_write_result=None) -> MagicMock:
    """Build a mock AsyncDatabase with decisions and cluster_sizes collections."""
    if bulk_write_result is None:
        bulk_write_result = _make_bulk_write_result()

    decisions_col = MagicMock()
    decisions_col.aggregate = AsyncMock(return_value=_make_async_cursor(aggregate_rows))

    cluster_sizes_col = AsyncMock()
    cluster_sizes_col.bulk_write = AsyncMock(return_value=bulk_write_result)
    cluster_sizes_col.delete_many = AsyncMock()

    db = MagicMock()

    def _getitem(name):
        if name == "decisions":
            return decisions_col
        if name == "cluster_sizes":
            return cluster_sizes_col
        raise KeyError(name)

    db.__getitem__ = MagicMock(side_effect=_getitem)
    return db


# ── _aggregate_cluster_counts ─────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aggregate_cluster_counts_groups_by_cluster_id():
    """Rows with valid string _id are returned as {cluster_id: count}."""
    rows = [{"_id": "A", "count": 3}, {"_id": "B", "count": 1}]
    db = _make_db(aggregate_rows=rows)

    result = await _aggregate_cluster_counts(db)

    assert result == {"A": 3, "B": 1}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aggregate_cluster_counts_skips_null_cluster_id():
    """Rows where _id is None are silently skipped."""
    rows = [{"_id": None, "count": 5}, {"_id": "C", "count": 2}]
    db = _make_db(aggregate_rows=rows)

    result = await _aggregate_cluster_counts(db)

    assert result == {"C": 2}
    assert None not in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aggregate_cluster_counts_empty_collection():
    """Empty aggregate result returns an empty dict."""
    db = _make_db(aggregate_rows=[])

    result = await _aggregate_cluster_counts(db)

    assert result == {}


# ── _build_upsert_ops ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_build_upsert_ops_creates_upsert_for_each_cluster():
    """Each cluster produces an UpdateOne with $set.size and $setOnInsert._id."""
    counts = {"A": 3, "B": 1}

    ops = _build_upsert_ops(counts)

    assert len(ops) == 2
    for op in ops:
        assert isinstance(op, UpdateOne)
        update_doc = op._doc
        assert "size" in update_doc["$set"]
        assert "_id" in update_doc["$setOnInsert"]

    sizes = {op._doc["$setOnInsert"]["_id"]: op._doc["$set"]["size"] for op in ops}
    assert sizes == {"A": 3, "B": 1}


# ── _run_backfill ─────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_backfill_dry_run_does_not_write():
    """In dry-run mode neither bulk_write nor delete_many is called."""
    rows = [{"_id": "A", "count": 2}, {"_id": "B", "count": 7}]
    db = _make_db(aggregate_rows=rows)
    cluster_sizes_col = db["cluster_sizes"]

    await _run_backfill(db, dry_run=True, batch_size=500)

    cluster_sizes_col.bulk_write.assert_not_called()
    cluster_sizes_col.delete_many.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_backfill_writes_upserts_in_batches():
    """5 clusters with batch_size=2 results in 3 bulk_write calls."""
    rows = [{"_id": str(i), "count": i + 1} for i in range(5)]
    db = _make_db(aggregate_rows=rows)
    cluster_sizes_col = db["cluster_sizes"]

    await _run_backfill(db, dry_run=False, batch_size=2)

    assert cluster_sizes_col.bulk_write.call_count == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_backfill_empty_decisions_makes_no_writes():
    """When there are no decisions, bulk_write and delete_many are never called."""
    db = _make_db(aggregate_rows=[])
    cluster_sizes_col = db["cluster_sizes"]

    await _run_backfill(db, dry_run=False, batch_size=500)

    cluster_sizes_col.bulk_write.assert_not_called()
    cluster_sizes_col.delete_many.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_backfill_deletes_stale_entries():
    """After upserting, delete_many is called once with a $nin filter.

    'A' is the only live cluster; it MUST appear in the $nin exclusion list so
    that only documents whose _id is not in the live set are removed.
    """
    rows = [{"_id": "A", "count": 1}]
    db = _make_db(aggregate_rows=rows)
    cluster_sizes_col = db["cluster_sizes"]

    await _run_backfill(db, dry_run=False, batch_size=500)

    cluster_sizes_col.delete_many.assert_called_once()
    delete_filter = cluster_sizes_col.delete_many.call_args[0][0]
    assert "$nin" in delete_filter["_id"]
    # "A" is a live cluster: it MUST appear in the $nin exclusion list so it is
    # preserved (only documents whose _id is NOT in live_cluster_ids are deleted).
    assert "A" in delete_filter["_id"]["$nin"]
