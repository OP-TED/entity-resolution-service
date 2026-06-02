"""Unit tests for MongoClusterSizeIndex adapter."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from ers.resolution_decision_store.adapters.cluster_size_index import MongoClusterSizeIndex


def make_collection() -> MagicMock:
    """Create a mock AsyncCollection for MongoClusterSizeIndex."""
    col = MagicMock()
    col.bulk_write = AsyncMock(return_value=MagicMock())
    col.find_one = AsyncMock(return_value=None)
    return col


def make_index(collection: MagicMock | None = None) -> MongoClusterSizeIndex:
    if collection is None:
        collection = make_collection()
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=collection)
    return MongoClusterSizeIndex(db)


# ---------------------------------------------------------------------------
# shift — insert path (from_cluster=None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shift_insert_path_emits_single_increment_upsert():
    """shift(from=None, to=X) issues one UpdateOne for X only."""
    col = make_collection()
    index = make_index(col)

    await index.shift(from_cluster=None, to_cluster="cluster-X")

    col.bulk_write.assert_awaited_once()
    ops = col.bulk_write.call_args[0][0]
    assert len(ops) == 1
    # The single op must increment cluster-X
    op_filter = ops[0]._filter  # type: ignore[attr-defined]
    op_update = ops[0]._doc  # type: ignore[attr-defined]
    assert op_filter == {"_id": "cluster-X"}
    assert op_update["$inc"]["size"] == 1


@pytest.mark.asyncio
async def test_shift_insert_path_uses_set_on_insert():
    """shift(from=None, to=X) uses $setOnInsert to avoid overwriting existing size."""
    col = make_collection()
    index = make_index(col)

    await index.shift(from_cluster=None, to_cluster="cluster-X")

    ops = col.bulk_write.call_args[0][0]
    op_update = ops[0]._doc  # type: ignore[attr-defined]
    # $setOnInsert must set _id to avoid the default ObjectId on insert
    assert "$setOnInsert" in op_update


# ---------------------------------------------------------------------------
# shift — both clusters (placement change)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shift_both_clusters_emits_two_ops_in_one_bulk_write():
    """shift(from=X, to=Y) issues two UpdateOne ops in a single bulk_write."""
    col = make_collection()
    index = make_index(col)

    await index.shift(from_cluster="cluster-X", to_cluster="cluster-Y")

    col.bulk_write.assert_awaited_once()
    ops = col.bulk_write.call_args[0][0]
    assert len(ops) == 2


@pytest.mark.asyncio
async def test_shift_both_clusters_decrements_from_and_increments_to():
    """shift(from=X, to=Y) decrements X and increments Y."""
    col = make_collection()
    index = make_index(col)

    await index.shift(from_cluster="cluster-X", to_cluster="cluster-Y")

    ops = col.bulk_write.call_args[0][0]
    filters = [op._filter for op in ops]  # type: ignore[attr-defined]
    updates = [op._doc for op in ops]  # type: ignore[attr-defined]

    # Find the decrement op
    from_op = next(
        u for f, u in zip(filters, updates, strict=True) if f == {"_id": "cluster-X"}
    )
    to_op = next(
        u for f, u in zip(filters, updates, strict=True) if f == {"_id": "cluster-Y"}
    )

    assert from_op["$inc"]["size"] == -1
    assert to_op["$inc"]["size"] == 1


# ---------------------------------------------------------------------------
# shift — same cluster (no-op)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shift_same_cluster_is_no_op():
    """shift(from=X, to=X) must not call bulk_write at all."""
    col = make_collection()
    index = make_index(col)

    await index.shift(from_cluster="cluster-X", to_cluster="cluster-X")

    col.bulk_write.assert_not_awaited()


# ---------------------------------------------------------------------------
# shift — removal path (to_cluster=None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shift_removal_path_emits_single_decrement_upsert():
    """shift(from=X, to=None) issues one UpdateOne for X only (removal path)."""
    col = make_collection()
    index = make_index(col)

    await index.shift(from_cluster="cluster-X", to_cluster=None)

    col.bulk_write.assert_awaited_once()
    ops = col.bulk_write.call_args[0][0]
    assert len(ops) == 1
    op_filter = ops[0]._filter  # type: ignore[attr-defined]
    op_update = ops[0]._doc  # type: ignore[attr-defined]
    assert op_filter == {"_id": "cluster-X"}
    assert op_update["$inc"]["size"] == -1


# ---------------------------------------------------------------------------
# shift — both None (edge case)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shift_both_none_is_no_op():
    """shift(from=None, to=None) must not call bulk_write."""
    col = make_collection()
    index = make_index(col)

    await index.shift(from_cluster=None, to_cluster=None)

    col.bulk_write.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_size
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_size_returns_zero_for_absent_cluster():
    """get_size returns 0 when the cluster is not in the index."""
    col = make_collection()
    col.find_one = AsyncMock(return_value=None)
    index = make_index(col)

    result = await index.get_size("missing-cluster")

    assert result == 0


@pytest.mark.asyncio
async def test_get_size_returns_stored_value():
    """get_size returns the size from the stored document."""
    col = make_collection()
    col.find_one = AsyncMock(return_value={"_id": "cluster-A", "size": 42})
    index = make_index(col)

    result = await index.get_size("cluster-A")

    assert result == 42


@pytest.mark.asyncio
async def test_get_size_queries_by_cluster_id():
    """get_size queries the collection using the cluster_id as _id."""
    col = make_collection()
    col.find_one = AsyncMock(return_value=None)
    index = make_index(col)

    await index.get_size("cluster-Z")

    col.find_one.assert_awaited_once()
    call_args = col.find_one.call_args
    assert call_args[0][0] == {"_id": "cluster-Z"}
