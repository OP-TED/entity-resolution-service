"""Unit tests for the curation-owned MongoReviewStateReader (A1).

The reader computes ``reviewed_since_placement`` from the ``user_actions``
collection (owned by curation), replacing the cross-collection read that
previously lived inside the decision-store adapter.
"""
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers.curation.adapters.review_state_reader import MongoReviewStateReader


def make_identifier(source_id="s1", request_id="r1", entity_type="Person"):
    return EntityMentionIdentifier(
        source_id=source_id, request_id=request_id, entity_type=entity_type
    )


def make_cluster(cluster_id="c1"):
    return ClusterReference(cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85)


def _make_async_cursor(items: list):
    class _Cursor:
        def __init__(self, data):
            self._data = list(data)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._data:
                raise StopAsyncIteration
            return self._data.pop(0)

    return _Cursor(items)


def make_reader(ua_collection: MagicMock) -> MongoReviewStateReader:
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=ua_collection)
    return MongoReviewStateReader(db)


@pytest.mark.asyncio
async def test_reviewed_since_placement_maps_matches():
    """True only for decisions whose triad has a user_action since placement."""
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

    ua_collection = MagicMock()
    ua_collection.find = MagicMock(
        return_value=_make_async_cursor(
            [{"about_entity_mention": {"source_id": "s1", "request_id": "r1",
                                       "entity_type": "Person"}}]
        )
    )
    reader = make_reader(ua_collection)

    result = await reader.reviewed_since_placement([reviewed, pending])

    assert result == {"hash-reviewed": True, "hash-pending": False}
    # Reads the curation-owned user_actions collection.
    db = ua_collection
    ua_query = db.find.call_args[0][0]
    assert "$or" in ua_query and len(ua_query["$or"]) == 2


@pytest.mark.asyncio
async def test_reviewed_since_placement_uses_strict_gt_boundary():
    """The "since placement" predicate uses strict ``$gt`` on created_at."""
    placement = datetime(2026, 6, 2, 12, 0, 0, tzinfo=UTC)
    decision = Decision(
        id="hash-1",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster(),
        candidates=[],
        created_at=placement,
        updated_at=placement,
    )
    ua_collection = MagicMock()
    ua_collection.find = MagicMock(return_value=_make_async_cursor([]))
    reader = make_reader(ua_collection)

    await reader.reviewed_since_placement([decision])

    clause = ua_collection.find.call_args[0][0]["$or"][0]
    assert clause["created_at"] == {"$gt": placement}


@pytest.mark.asyncio
async def test_reviewed_since_placement_empty_input():
    """Empty input returns an empty mapping without querying."""
    ua_collection = MagicMock()
    reader = make_reader(ua_collection)

    assert await reader.reviewed_since_placement([]) == {}
    ua_collection.find.assert_not_called()
