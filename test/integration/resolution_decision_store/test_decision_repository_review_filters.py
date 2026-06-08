"""Integration tests for the review-state filters of find_with_filters.

Proves on the real engine (FerretDB) that the filters now run as plain
``$match`` predicates on stored fields (no ``$lookup user_actions``):

- ``ever_reviewed`` partitioning, including documents with a *missing* counter
  (the ``$in: [0, None]`` predicate),
- ``reviewed_since_placement`` partitioning on the stored boolean, including
  documents with a *missing* flag (the ``$in: [False, None]`` predicate),
- the combined "needs revisit" filter (``ever_reviewed=True`` +
  ``reviewed_since_placement=False``),
- ``CursorPage.count`` matches the filtered result set exactly (resolves A3 —
  the previous upper-bound contract is gone).
"""

from datetime import UTC, datetime, timedelta

import pytest
from erspec.models.core import ClusterReference, EntityMentionIdentifier

from ers.commons.domain.data_transfer_objects import CursorParams
from ers.curation.domain.data_transfer_objects import DecisionFilters
from ers.resolution_decision_store.adapters.decision_repository import (
    MongoDecisionRepository,
)

_T0 = datetime(2026, 6, 2, 12, 0, 0, tzinfo=UTC)


def _ident(source_id: str) -> EntityMentionIdentifier:
    return EntityMentionIdentifier(
        source_id=source_id, request_id="r1", entity_type="Person"
    )


def _cluster(cluster_id="c1") -> ClusterReference:
    return ClusterReference(
        cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.8
    )


@pytest.fixture()
async def repo(mongo_db):
    r = MongoDecisionRepository(mongo_db)
    await r.ensure_indexes()
    return r


@pytest.fixture()
async def seeded(repo, mongo_db):
    """Three decisions spanning the review-state partitions.

    - ``rev``     : reviewed, action after placement → ``ever=True``,  ``since=True``
    - ``revisit`` : reviewed, no action since placement → ``ever=True``,  ``since=False``
    - ``never``   : missing counter + missing flag → ``ever=False``, ``since=False``
    """
    rev = await repo.upsert_decision(_ident("s-rev"), _cluster(), [], _T0)
    revisit = await repo.upsert_decision(_ident("s-revisit"), _cluster(), [], _T0)
    never = await repo.upsert_decision(_ident("s-never"), _cluster(), [], _T0)

    # Materialise the primitives via the production writer.
    await repo.record_review(rev.id, _T0 + timedelta(seconds=10))
    await repo.record_review(revisit.id, _T0 + timedelta(seconds=10))

    # Re-integrate ``revisit`` (material placement change) so the integrator's
    # $set false fires, leaving the row in the "needs revisit" partition.
    await repo.upsert_decision(
        _ident("s-revisit"), _cluster("c2"), [], _T0 + timedelta(seconds=30)
    )

    # Strip the materialised fields off ``never`` so it represents the legacy
    # "missing field" case — exercising the ``$in [False, None]`` predicate.
    await mongo_db["decisions"].update_one(
        {"_id": never.id},
        {"$unset": {"previous_review_count": "", "reviewed_since_placement": ""}},
    )

    return {"rev": rev.id, "revisit": revisit.id, "never": never.id}


async def _page(repo, **kwargs):
    return await repo.find_with_filters(
        filters=DecisionFilters(), cursor_params=CursorParams(limit=50), **kwargs
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ever_reviewed_true_returns_counted(repo, seeded):
    page = await _page(repo, ever_reviewed=True)
    assert {d.id for d in page.results} == {seeded["rev"], seeded["revisit"]}
    assert page.count == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ever_reviewed_false_matches_missing_counter(repo, seeded):
    page = await _page(repo, ever_reviewed=False)
    assert {d.id for d in page.results} == {seeded["never"]}
    assert page.count == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reviewed_since_placement_true(repo, seeded):
    page = await _page(repo, reviewed_since_placement=True)
    assert {d.id for d in page.results} == {seeded["rev"]}
    assert page.count == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reviewed_since_placement_false_matches_missing_field(repo, seeded):
    page = await _page(repo, reviewed_since_placement=False)
    assert {d.id for d in page.results} == {seeded["revisit"], seeded["never"]}
    assert page.count == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_needs_revisit_combined_filter(repo, seeded):
    """ever_reviewed=True AND reviewed_since_placement=False → "needs revisit".

    Single ``find()`` query with two stored-field predicates; ``count`` is
    exact across the same predicate set."""
    page = await _page(repo, ever_reviewed=True, reviewed_since_placement=False)
    assert {d.id for d in page.results} == {seeded["revisit"]}
    assert page.count == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_find_by_id_returns_reviewed_decision_without_materialised_fields(
    repo, seeded
):
    """``_from_document`` must strip both materialised fields before model validation."""
    decision = await repo.find_by_id(seeded["rev"])
    assert decision is not None
    assert decision.id == seeded["rev"]
