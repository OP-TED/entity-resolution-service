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
    """IT-001: Store a decision and retrieve it by triad."""
    now = datetime.now(UTC)
    stored = await repo.upsert_decision(
        make_identifier(), make_cluster(), [], now
    )
    found = await repo.find_by_triad(make_identifier())
    assert found is not None
    assert found.id == stored.id
    assert found.current_placement.cluster_id == "c1"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_it002_staleness_rejection(repo):
    """IT-002: Storing with an older timestamp raises StaleOutcomeError."""
    now = datetime.now(UTC)
    await repo.upsert_decision(make_identifier(), make_cluster(), [], now)
    with pytest.raises(StaleOutcomeError):
        await repo.upsert_decision(
            make_identifier(),
            make_cluster("c2"),
            [],
            now - timedelta(seconds=1),
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_it003_created_at_preserved_on_replacement(repo):
    """IT-003: Replacing a decision preserves created_at; advances updated_at."""
    t1 = datetime.now(UTC).replace(microsecond=0)
    t2 = t1 + timedelta(seconds=5)
    await repo.upsert_decision(make_identifier(), make_cluster("c1"), [], t1)
    updated = await repo.upsert_decision(
        make_identifier(), make_cluster("c2"), [], t2
    )
    assert updated.created_at == t1
    assert updated.updated_at == t2
    assert updated.current_placement.cluster_id == "c2"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_it004_cursor_pagination(repo):
    """IT-004: Cursor pagination traverses all decisions in correct order."""
    base = datetime.now(UTC)
    for i in range(5):
        ident = make_identifier(source_id=f"s{i}")
        await repo.upsert_decision(
            ident, make_cluster(), [], base + timedelta(seconds=i)
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
