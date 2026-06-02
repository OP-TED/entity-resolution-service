"""Integration tests for MongoReviewStateReader against a real engine (FerretDB).

Proves the ``$or``-of-subdocuments + strict ``$gt`` boundary on the production
engine (A1 read-port move; A5 boundary; A2 action-straddling-the-boundary).
"""
from datetime import UTC, datetime, timedelta

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers.curation.adapters.review_state_reader import MongoReviewStateReader

_COLLECTION_USER_ACTIONS = "user_actions"
_PLACEMENT = datetime(2026, 6, 2, 12, 0, 0, tzinfo=UTC)


def _make_decision(decision_id: str, since: datetime, source_id="s1", request_id="r1") -> Decision:
    return Decision(
        id=decision_id,
        about_entity_mention=EntityMentionIdentifier(
            source_id=source_id, request_id=request_id, entity_type="Person"
        ),
        current_placement=ClusterReference(
            cluster_id="c1", confidence_score=0.9, similarity_score=0.8
        ),
        candidates=[],
        created_at=since,
        updated_at=since,
    )


async def _insert_action(mongo_db, source_id, request_id, created_at) -> None:
    await mongo_db[_COLLECTION_USER_ACTIONS].insert_one(
        {
            "about_entity_mention": {
                "source_id": source_id,
                "request_id": request_id,
                "entity_type": "Person",
            },
            "created_at": created_at,
        }
    )


@pytest.fixture()
async def reader(mongo_db):
    return MongoReviewStateReader(mongo_db)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_action_after_placement_is_reviewed(reader, mongo_db):
    decision = _make_decision("d1", _PLACEMENT)
    await _insert_action(mongo_db, "s1", "r1", _PLACEMENT + timedelta(seconds=1))

    assert await reader.reviewed_since_placement([decision]) == {"d1": True}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_action_at_exact_placement_is_not_reviewed(reader, mongo_db):
    """A5 boundary: strict ``$gt`` — an action at the exact placement instant
    does not count as "since placement"."""
    decision = _make_decision("d1", _PLACEMENT)
    await _insert_action(mongo_db, "s1", "r1", _PLACEMENT)

    assert await reader.reviewed_since_placement([decision]) == {"d1": False}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_action_before_placement_is_not_reviewed(reader, mongo_db):
    decision = _make_decision("d1", _PLACEMENT)
    await _insert_action(mongo_db, "s1", "r1", _PLACEMENT - timedelta(seconds=1))

    assert await reader.reviewed_since_placement([decision]) == {"d1": False}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_action_is_not_reviewed(reader):
    decision = _make_decision("d1", _PLACEMENT)
    assert await reader.reviewed_since_placement([decision]) == {"d1": False}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mixed_page_maps_each_decision(reader, mongo_db):
    reviewed = _make_decision("d-rev", _PLACEMENT, source_id="s1", request_id="r1")
    pending = _make_decision("d-pend", _PLACEMENT, source_id="s2", request_id="r2")
    await _insert_action(mongo_db, "s1", "r1", _PLACEMENT + timedelta(seconds=1))

    result = await reader.reviewed_since_placement([reviewed, pending])

    assert result == {"d-rev": True, "d-pend": False}
