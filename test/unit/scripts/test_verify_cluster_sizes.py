"""Unit tests for scripts.verify_cluster_sizes."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.verify_cluster_sizes import _verify


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_async_cursor(docs: list):
    """Return an async-iterable object yielding docs one by one."""

    class _AsyncCursor:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            for doc in docs:
                yield doc

    return _AsyncCursor()


def _make_db(aggregate_rows: list, projection_docs: list) -> MagicMock:
    """Build a mock AsyncDatabase for _verify tests.

    decisions.aggregate() returns aggregate_rows via .to_list().
    cluster_sizes.find() returns an async cursor over projection_docs.
    """
    decisions_cursor = AsyncMock()
    decisions_cursor.to_list = AsyncMock(return_value=aggregate_rows)
    decisions_col = MagicMock()
    decisions_col.aggregate = AsyncMock(return_value=decisions_cursor)

    cluster_sizes_col = MagicMock()
    cluster_sizes_col.find = MagicMock(return_value=_make_async_cursor(projection_docs))

    db = MagicMock()

    def _getitem(name):
        if name == "decisions":
            return decisions_col
        if name == "cluster_sizes":
            return cluster_sizes_col
        raise KeyError(name)

    db.__getitem__ = MagicMock(side_effect=_getitem)
    return db


# ── _verify ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_consistent_returns_true():
    """Matching count in decisions and size in cluster_sizes returns True."""
    db = _make_db(
        aggregate_rows=[{"_id": "A", "count": 2}],
        projection_docs=[{"_id": "A", "size": 2}],
    )

    result = await _verify(db, verbose=False)

    assert result is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_missing_projection_entry_returns_false():
    """A cluster in decisions with no cluster_sizes entry is drift — returns False."""
    db = _make_db(
        aggregate_rows=[{"_id": "A", "count": 2}],
        projection_docs=[],
    )

    result = await _verify(db, verbose=False)

    assert result is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_stale_projection_entry_returns_false():
    """A cluster in cluster_sizes absent from decisions is stale — returns False."""
    db = _make_db(
        aggregate_rows=[],
        projection_docs=[{"_id": "X", "size": 3}],
    )

    result = await _verify(db, verbose=False)

    assert result is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_mismatched_count_returns_false():
    """Count in decisions differs from size in cluster_sizes — returns False."""
    db = _make_db(
        aggregate_rows=[{"_id": "A", "count": 5}],
        projection_docs=[{"_id": "A", "size": 3}],
    )

    result = await _verify(db, verbose=False)

    assert result is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_both_empty_returns_true():
    """No clusters in either collection means projection is consistent — returns True."""
    db = _make_db(
        aggregate_rows=[],
        projection_docs=[],
    )

    result = await _verify(db, verbose=False)

    assert result is True
