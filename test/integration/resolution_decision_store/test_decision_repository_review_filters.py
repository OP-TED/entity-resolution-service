"""Integration tests for the review-state filters of find_with_filters (A2).

Proves on the real engine (FerretDB):
- ``ever_reviewed`` partitioning, including documents with a *missing* counter
  (the ``$in: [0, None]`` predicate), and
- ``reviewed_since_placement`` via the ``user_actions`` ``$lookup`` aggregation,
- the combined "needs revisit" filter (ever_reviewed=True + since=False).
"""
from datetime import UTC, datetime, timedelta

import pytest
from erspec.models.core import ClusterReference, EntityMentionIdentifier

from ers.commons.domain.data_transfer_objects import CursorParams
from ers.curation.domain.data_transfer_objects import DecisionFilters
from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository

_T0 = datetime(2026, 6, 2, 12, 0, 0, tzinfo=UTC)
_COLLECTION_USER_ACTIONS = "user_actions"


def _ident(source_id: str) -> EntityMentionIdentifier:
    return EntityMentionIdentifier(
        source_id=source_id, request_id="r1", entity_type="Person"
    )


def _cluster(cluster_id="c1") -> ClusterReference:
    return ClusterReference(cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.8)


async def _insert_action(mongo_db, source_id: str, created_at: datetime) -> None:
    await mongo_db[_COLLECTION_USER_ACTIONS].insert_one(
        {
            "about_entity_mention": {
                "source_id": source_id,
                "request_id": "r1",
                "entity_type": "Person",
            },
            "created_at": created_at,
        }
    )


@pytest.fixture()
async def repo(mongo_db):
    r = MongoDecisionRepository(mongo_db)
    await r.ensure_indexes()
    return r


@pytest.fixture()
async def seeded(repo, mongo_db):
    """Three decisions spanning the review-state partitions.

    - ``rev``     : reviewed, with an action after placement  → ever=True,  since=True
    - ``revisit`` : reviewed, no action since placement        → ever=True,  since=False
    - ``never``   : missing counter, no action                 → ever=False, since=False
    """
    rev = await repo.upsert_decision(_ident("s-rev"), _cluster(), [], _T0)
    revisit = await repo.upsert_decision(_ident("s-revisit"), _cluster(), [], _T0)
    never = await repo.upsert_decision(_ident("s-never"), _cluster(), [], _T0)

    await repo.increment_review_count(rev.id)
    await repo.increment_review_count(revisit.id)
    # ``never`` keeps a missing previous_review_count field.

    await _insert_action(mongo_db, "s-rev", _T0 + timedelta(seconds=10))

    return {"rev": rev.id, "revisit": revisit.id, "never": never.id}


async def _ids(repo, **kwargs) -> set[str]:
    page = await repo.find_with_filters(
        filters=DecisionFilters(), cursor_params=CursorParams(limit=50), **kwargs
    )
    return {d.id for d in page.results}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ever_reviewed_true_returns_counted(repo, seeded):
    assert await _ids(repo, ever_reviewed=True) == {seeded["rev"], seeded["revisit"]}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ever_reviewed_false_matches_missing_counter(repo, seeded):
    # The $in:[0,None] predicate must match the document with no counter field.
    assert await _ids(repo, ever_reviewed=False) == {seeded["never"]}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reviewed_since_placement_true(repo, seeded):
    assert await _ids(repo, reviewed_since_placement=True) == {seeded["rev"]}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reviewed_since_placement_false(repo, seeded):
    assert await _ids(repo, reviewed_since_placement=False) == {
        seeded["revisit"],
        seeded["never"],
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_needs_revisit_combined_filter(repo, seeded):
    # ever_reviewed=True AND reviewed_since_placement=False  → "needs revisit".
    assert await _ids(repo, ever_reviewed=True, reviewed_since_placement=False) == {
        seeded["revisit"]
    }
