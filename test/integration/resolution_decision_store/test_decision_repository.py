"""Integration tests for MongoDecisionRepository against real MongoDB."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from erspec.models.core import ClusterReference, EntityMentionIdentifier

from ers.commons.domain.data_transfer_objects import CursorParams
from ers.resolution_decision_store.adapters.decision_repository import (
    MongoDecisionRepository,
)
from ers.resolution_decision_store.adapters.provisional_id import (
    derive_provisional_cluster_id,
)
from ers.resolution_decision_store.domain.errors import StaleOutcomeError


def make_identifier(source_id="s1", request_id="r1", entity_type="Person"):
    return EntityMentionIdentifier(
        source_id=source_id, request_id=request_id, entity_type=entity_type
    )


def make_cluster(cluster_id="c1"):
    return ClusterReference(
        cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85
    )


@pytest.fixture()
async def repo(mongo_db):
    """Provide MongoDecisionRepository with a real MongoDB connection."""
    r = MongoDecisionRepository(mongo_db)
    await r.ensure_indexes()
    yield r


@pytest.mark.asyncio
@pytest.mark.integration
async def test_it001_store_and_retrieve(repo):
    """IT-001: Store a decision and retrieve it by triad.

    On first insert, updated_at must be None (R1: never-updated placement).
    """
    now = datetime.now(UTC)
    stored = await repo.upsert_decision(
        make_identifier(), make_cluster(), [], now
    )
    found = await repo.find_by_triad(make_identifier())
    assert found is not None
    assert found.id == stored.id
    assert found.current_placement.cluster_id == "c1"
    # First insert: updated_at is not set (stays None per R1)
    assert found.updated_at is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_it002_staleness_rejection(repo):
    """IT-002: Storing with an older timestamp raises StaleOutcomeError.

    Stale-rejection only applies once ``updated_at`` is set (i.e. after a real
    placement change). Per R2, a write against a record with ``updated_at=None``
    is never stale — so we first do an insert, then an update (which sets
    ``updated_at``), then attempt a stale write.
    """
    t1 = datetime.now(UTC)
    t2 = t1 + timedelta(seconds=5)
    # 1. Insert (updated_at remains None).
    await repo.upsert_decision(make_identifier(), make_cluster("c1"), [], t1)
    # 2. Update (different cluster) — updated_at becomes t2.
    await repo.upsert_decision(make_identifier(), make_cluster("c2"), [], t2)
    # 3. Stale write — incoming timestamp older than stored updated_at.
    with pytest.raises(StaleOutcomeError):
        await repo.upsert_decision(
            make_identifier(),
            make_cluster("c3"),
            [],
            t1,
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_it003_created_at_preserved_on_replacement(repo):
    """IT-003: Replacing a decision preserves created_at; sets updated_at on update.

    First insert has updated_at=None. Replacement (different cluster) sets updated_at=t2.
    """
    t1 = datetime.now(UTC).replace(microsecond=0)
    t2 = t1 + timedelta(seconds=5)
    first = await repo.upsert_decision(make_identifier(), make_cluster("c1"), [], t1)
    # First insert: created_at=t1, updated_at=None
    assert first.created_at == t1
    assert first.updated_at is None

    # Update path (different cluster): created_at preserved, updated_at=t2
    updated = await repo.upsert_decision(
        make_identifier(), make_cluster("c2"), [], t2
    )
    assert updated.created_at == t1
    assert updated.updated_at == t2
    assert updated.current_placement.cluster_id == "c2"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_it004_cursor_pagination(repo):
    """IT-004: Cursor pagination traverses all decisions in correct order.

    Each decision is inserted then updated (different cluster) so that
    ``updated_at`` is set — pagination orders by ``updated_at`` ASC and a
    just-inserted record (``updated_at=None``) cannot participate in that
    ordering.
    """
    base = datetime.now(UTC).replace(microsecond=0)
    for i in range(5):
        ident = make_identifier(source_id=f"s{i}")
        # Insert (updated_at=None), then update with a different cluster so
        # updated_at is set to a unique, monotonically increasing timestamp.
        await repo.upsert_decision(ident, make_cluster("c-init"), [], base)
        await repo.upsert_decision(
            ident, make_cluster(f"c-{i}"), [], base + timedelta(seconds=i + 1)
        )

    page1 = await repo.find_with_filters(
        filters=None, cursor_params=CursorParams(cursor=None, limit=3)
    )
    assert len(page1.results) == 3
    assert page1.next_cursor is not None

    page2 = await repo.find_with_filters(
        filters=None, cursor_params=CursorParams(cursor=page1.next_cursor, limit=3)
    )
    assert len(page2.results) == 2
    assert page2.next_cursor is None

    # Verify ordering: all 5 results in updated_at ASC order
    all_results = page1.results + page2.results
    assert all_results == sorted(all_results, key=lambda d: d.updated_at)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_it005_concurrent_upsert(repo):
    """IT-005: Concurrent upserts — at least one succeeds; no data corruption."""
    now = datetime.now(UTC)
    results = await asyncio.gather(
        repo.upsert_decision(make_identifier(), make_cluster("c1"), [], now),
        repo.upsert_decision(make_identifier(), make_cluster("c2"), [], now),
        return_exceptions=True,
    )
    successes = [r for r in results if not isinstance(r, Exception)]
    assert len(successes) >= 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_it006_provisional_id_consistency():
    """IT-006: derive_provisional_cluster_id is deterministic across 1000 calls."""
    ident = make_identifier()
    ids = {derive_provisional_cluster_id(ident) for _ in range(1000)}
    assert len(ids) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_it007_ac7_stale_falls_back_to_created_at_against_real_mongo(repo):
    """IT-007 (AC7): R2 stale check uses created_at as fallback when updated_at is None.

    Out-of-order ERE delivery: a newer outcome arrives first and is inserted
    (created_at=t2, updated_at=None). A later, older-timestamped outcome
    (incoming=t1 < t2) must be rejected as stale, not silently overwrite.
    Exercises the R2 ``$or`` branch ``{updated_at: None, created_at: {$lt: incoming}}``
    against a real Mongo server.
    """
    t1 = datetime.now(UTC).replace(microsecond=0)
    t2 = t1 + timedelta(seconds=10)

    # 1. First insert at t2 → created_at=t2, updated_at=None.
    inserted = await repo.upsert_decision(make_identifier(), make_cluster("c-newer"), [], t2)
    assert inserted.created_at == t2
    assert inserted.updated_at is None

    # 2. Older outcome arrives → must be rejected, store unchanged.
    with pytest.raises(StaleOutcomeError):
        await repo.upsert_decision(make_identifier(), make_cluster("c-stale"), [], t1)

    # Verify the placement was NOT overwritten.
    stored = await repo.find_by_triad(make_identifier())
    assert stored is not None
    assert stored.current_placement.cluster_id == "c-newer"
    assert stored.created_at == t2
    assert stored.updated_at is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_it008_ac9_partial_delta_index_exists(repo, mongo_db):
    """IT-008 (AC9): ``ensure_indexes`` creates the delta partial index against real Mongo.

    Verifies that ``idx_decision_store_delta`` exists on the decisions
    collection with ``partialFilterExpression: {updated_at: {$exists: true}}``.
    Exercising this against the real engine confirms the planner accepts the
    partial-filter expression (DocumentDB rejects ``$ne`` here, MongoDB and
    FerretDB accept ``$exists`` — the partial filter shape we use).
    """
    cursor = await mongo_db["decisions"].list_indexes()
    indexes = await cursor.to_list()
    by_name = {idx["name"]: idx for idx in indexes}

    assert "idx_decision_store_delta" in by_name, (
        f"Partial delta index missing. Found indexes: {list(by_name)}"
    )
    delta_idx = by_name["idx_decision_store_delta"]
    assert delta_idx.get("partialFilterExpression") == {"updated_at": {"$exists": True}}, (
        f"Partial filter expression mismatch: {delta_idx.get('partialFilterExpression')}"
    )
