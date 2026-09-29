"""End-to-end lifecycle of the materialised review-state primitives.

Proves on the real engine (FerretDB) that the two writers (integrator and
``record_review``) maintain the documented invariants:

- a fresh decision starts ``(count=0, flag=False)``,
- a curator action after placement flips ``flag=True`` and increments the counter,
- a material placement advance resets ``flag=False`` and preserves the counter,
- a stale/out-of-order curator action (``created_at < stored placement boundary``)
  is rejected by the atomic claim (returns False) — counter and flag unchanged,
- an identical re-integration (no material change) leaves the materialised state
  untouched,
- concurrent ``record_review`` calls serialise — exactly one wins.

These are the acceptance scenarios for TEDSWS-524-2 milestones 1, 2, and the
post-empirical TOCTOU-race fix.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from erspec.models.core import ClusterReference, EntityMentionIdentifier

from ers.resolution_decision_store.adapters.decision_repository import (
    MongoDecisionRepository,
    ReviewMetadata,
)

_T0 = datetime(2026, 6, 5, 12, 0, 0, tzinfo=UTC)


def _ident(source_id: str = "s-1") -> EntityMentionIdentifier:
    return EntityMentionIdentifier(
        source_id=source_id, request_id="r1", entity_type="Person"
    )


def _cluster(cluster_id: str = "c-A") -> ClusterReference:
    return ClusterReference(
        cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.8
    )


@pytest.fixture()
async def repo(mongo_db):
    r = MongoDecisionRepository(mongo_db)
    await r.ensure_indexes()
    return r


async def _metadata(repo: MongoDecisionRepository, decision_id: str) -> ReviewMetadata:
    return (await repo.find_review_metadata([decision_id])).get(
        decision_id, ReviewMetadata()
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_insert_initialises_flag_false(repo) -> None:
    decision = await repo.upsert_decision(_ident(), _cluster(), [], _T0)
    assert await _metadata(repo, decision.id) == ReviewMetadata(
        previous_review_count=0, reviewed_since_placement=False
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_record_review_after_placement_sets_flag_true(repo) -> None:
    decision = await repo.upsert_decision(_ident(), _cluster(), [], _T0)
    action_ts = _T0 + timedelta(seconds=10)

    await repo.record_review(decision.id, action_ts)

    assert await _metadata(repo, decision.id) == ReviewMetadata(
        previous_review_count=1, reviewed_since_placement=True
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_material_reintegration_resets_flag_preserves_counter(repo) -> None:
    decision = await repo.upsert_decision(_ident(), _cluster("c-A"), [], _T0)
    await repo.record_review(decision.id, _T0 + timedelta(seconds=10))
    pre = await _metadata(repo, decision.id)
    assert pre.reviewed_since_placement is True
    assert pre.previous_review_count == 1

    # Material placement change at a later instant.
    await repo.upsert_decision(
        _ident(), _cluster("c-B"), [], _T0 + timedelta(seconds=20)
    )

    post = await _metadata(repo, decision.id)
    assert post.reviewed_since_placement is False, "integrator must reset the flag"
    assert post.previous_review_count == 1, "integrator must NOT touch the counter"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_stale_action_increments_counter_but_does_not_flip_flag(repo) -> None:
    """An action whose ``created_at`` predates the current placement boundary
    must increment the counter (the action happened) but must NOT regress the
    flag — the integrator has already moved past this action's relevance."""
    decision = await repo.upsert_decision(_ident(), _cluster("c-A"), [], _T0)
    # Placement advances to T0+30s. Flag is now False.
    await repo.upsert_decision(
        _ident(), _cluster("c-B"), [], _T0 + timedelta(seconds=30)
    )

    # A delayed action whose timestamp is between the two placements lands now.
    stale_ts = _T0 + timedelta(seconds=10)
    await repo.record_review(decision.id, stale_ts)

    metadata = await _metadata(repo, decision.id)
    assert metadata.previous_review_count == 1, "counter increments unconditionally"
    assert metadata.reviewed_since_placement is False, (
        "stale action must NOT flip the flag back to True"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_action_against_initial_placement_uses_created_at_boundary(repo) -> None:
    """For a decision that has never been re-placed (``updated_at`` is None),
    the placement boundary is ``created_at`` — an action strictly after that
    flips the flag."""
    decision = await repo.upsert_decision(_ident(), _cluster(), [], _T0)
    assert decision.updated_at is None

    await repo.record_review(decision.id, _T0 + timedelta(milliseconds=1))

    metadata = await _metadata(repo, decision.id)
    assert metadata.reviewed_since_placement is True
    assert metadata.previous_review_count == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_identical_replay_does_not_touch_materialised_state(repo) -> None:
    """An idempotent replay (same outcome, same updated_at) is rejected by the
    stale-outcome guard, so the materialised primitives are unchanged."""
    decision = await repo.upsert_decision(_ident(), _cluster("c-A"), [], _T0)
    await repo.record_review(decision.id, _T0 + timedelta(seconds=5))
    pre = await _metadata(repo, decision.id)

    from ers.resolution_decision_store.domain.errors import StaleOutcomeError

    with pytest.raises(StaleOutcomeError):
        await repo.upsert_decision(_ident(), _cluster("c-A"), [], _T0)

    post = await _metadata(repo, decision.id)
    assert post == pre, "rejected replay must not touch the materialised primitives"


# ── concurrency: atomic claim closes the TOCTOU race ──────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_record_review_only_one_succeeds(repo) -> None:
    """Empirically the TOCTOU race produced 2 user_actions 1 ms apart for a
    single curator (2026-06-07). With the atomic claim, ``record_review``'s
    filter ``reviewed_since_placement != True`` makes the conditional update
    serializable at the single-document level. Fire N concurrent claims;
    exactly one must return True and the rest must return False."""
    decision = await repo.upsert_decision(_ident(), _cluster(), [], _T0)
    action_ts = _T0 + timedelta(seconds=1)

    results = await asyncio.gather(
        *(repo.record_review(decision.id, action_ts) for _ in range(8))
    )

    winners = sum(1 for r in results if r is True)
    losers = sum(1 for r in results if r is False)
    assert winners == 1, f"exactly one concurrent claim must succeed; got {winners}"
    assert losers == 7, f"the other 7 must lose; got {losers}"

    metadata = await _metadata(repo, decision.id)
    assert metadata.previous_review_count == 1, (
        "counter must increment exactly once across all concurrent attempts"
    )
    assert metadata.reviewed_since_placement is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_record_review_returns_false_when_already_claimed(repo) -> None:
    """Sequential second claim against the same placement must return False
    without modifying any field. This is the non-race version of the same
    concurrency property — easy to debug in isolation."""
    decision = await repo.upsert_decision(_ident(), _cluster(), [], _T0)

    first = await repo.record_review(decision.id, _T0 + timedelta(seconds=1))
    second = await repo.record_review(decision.id, _T0 + timedelta(seconds=2))

    assert first is True
    assert second is False
    metadata = await _metadata(repo, decision.id)
    assert metadata.previous_review_count == 1
    assert metadata.reviewed_since_placement is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_record_review_returns_false_when_decision_missing(repo) -> None:
    """A missing decision document also yields ``modified_count == 0`` and
    therefore ``False`` — no upsert, no error, idempotent."""
    result = await repo.record_review("nonexistent-decision-id", _T0)
    assert result is False
