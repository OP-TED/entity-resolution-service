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
from ers.curation.adapters.review_state_reader import MongoReviewStateReader
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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_find_by_id_returns_reviewed_decision_without_counter(repo, seeded):
    """The previous_review_count strip (``_from_document``) must also hold on the
    single-document read path — reading a counter-bearing decision must validate."""
    decision = await repo.find_by_id(seeded["rev"])
    assert decision is not None
    assert decision.id == seeded["rev"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reintegration_preserves_counter_and_flips_reviewed(repo, mongo_db):
    """B5 acceptance: a material ERE re-integration preserves the review counter,
    advances ``updated_at``, and flips ``reviewed_since_placement`` back to False
    (the prior action now predates the new placement)."""
    reader = MongoReviewStateReader(mongo_db)
    t1 = _T0 + timedelta(seconds=5)
    t2 = _T0 + timedelta(seconds=10)

    decision = await repo.upsert_decision(_ident("s-re"), _cluster("A"), [], _T0)
    await repo.increment_review_count(decision.id)
    await _insert_action(mongo_db, "s-re", t1)

    reloaded = await repo.find_by_id(decision.id)
    assert await reader.reviewed_since_placement([reloaded]) == {decision.id: True}

    # ERE re-integration moves the placement (material change) at a later instant.
    updated = await repo.upsert_decision(_ident("s-re"), _cluster("B"), [], t2)

    assert (await repo.find_review_counts([decision.id])).get(decision.id) == 1
    assert updated.current_placement.cluster_id == "B"
    assert updated.updated_at == t2
    assert await reader.reviewed_since_placement([updated]) == {decision.id: False}
