"""Regression tests for cursor-seek helpers on MongoDecisionCurationRepository.

These tests exist to guarantee that lifting _build_cursor_condition and
_parse_cursor_sort_value to the MongoDecisionRepository base class does not
change observable behaviour for the curation repository.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock

from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository


def make_repo() -> MongoDecisionRepository:
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=MagicMock())
    return MongoDecisionRepository(db)


# ── _build_cursor_condition ───────────────────────────────────────────────────

def test_ascending_non_null_produces_or_with_gt():
    repo = make_repo()
    result = repo._build_cursor_condition("updated_at", "2025-01-01", "id123", ascending=True)
    assert "$or" in result
    assert {"updated_at": {"$gt": "2025-01-01"}} in result["$or"]
    assert {"updated_at": "2025-01-01", "_id": {"$gt": "id123"}} in result["$or"]


def test_descending_non_null_produces_or_with_lt():
    repo = make_repo()
    result = repo._build_cursor_condition("updated_at", "2025-01-01", "id123", ascending=False)
    assert "$or" in result
    assert {"updated_at": {"$lt": "2025-01-01"}} in result["$or"]
    assert {"updated_at": "2025-01-01", "_id": {"$lt": "id123"}} in result["$or"]


def test_ascending_null_value_includes_ne_none_branch():
    repo = make_repo()
    result = repo._build_cursor_condition("updated_at", None, "id123", ascending=True)
    assert "$or" in result
    or_clauses = result["$or"]
    assert {"updated_at": None, "_id": {"$gt": "id123"}} in or_clauses
    assert {"updated_at": {"$ne": None}} in or_clauses


def test_descending_null_value_restricts_to_null_field():
    repo = make_repo()
    result = repo._build_cursor_condition("updated_at", None, "id123", ascending=False)
    assert result == {"updated_at": None, "_id": {"$lt": "id123"}}


# ── _parse_cursor_sort_value ──────────────────────────────────────────────────

def test_datetime_field_returns_datetime_object():
    repo = make_repo()
    iso = "2025-06-01T12:00:00+00:00"
    result = repo._parse_cursor_sort_value(iso, "updated_at")
    assert isinstance(result, datetime)
    assert result == datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_created_at_also_parsed_as_datetime():
    repo = make_repo()
    iso = "2025-01-15T08:30:00+00:00"
    result = repo._parse_cursor_sort_value(iso, "created_at")
    assert isinstance(result, datetime)


def test_non_datetime_field_returned_as_is():
    repo = make_repo()
    result = repo._parse_cursor_sort_value(0.95, "current_placement.confidence_score")
    assert result == 0.95


def test_none_value_returned_as_none():
    repo = make_repo()
    result = repo._parse_cursor_sort_value(None, "updated_at")
    assert result is None
