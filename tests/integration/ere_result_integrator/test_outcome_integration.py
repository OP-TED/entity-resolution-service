"""Integration tests for OutcomeIntegrationService against real MongoDB and Redis.

Uses fixtures from:
  - tests/conftest.py: redis_client (function scope, flushes after each test)
  - tests/integration/conftest.py: mongo_db (function scope, drops DB after each test)
"""
from datetime import UTC, datetime, timedelta

import pytest
from erspec.models.core import ClusterReference, EntityMentionIdentifier
from erspec.models.ere import EntityMentionResolutionResponse

from ers.commons.adapters.hasher import SHA256ContentHasher
from ers.ere_result_integrator.services.outcome_integration_service import (
    OutcomeIntegrationService,
)
from ers.request_registry.adapters.records_repository import (
    MongoLookupStateRepository,
    MongoResolutionRequestRepository,
)
from ers.request_registry.domain.records import ResolutionRequestRecord
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_identifier(source="IT_SYS", req="req-it-001", entity="Organization"):
    return EntityMentionIdentifier(source_id=source, request_id=req, entity_type=entity)


def make_cluster(cluster_id="cluster-it-001", conf=0.95, sim=0.90):
    return ClusterReference(cluster_id=cluster_id, confidence_score=conf, similarity_score=sim)


def truncate_ms(dt: datetime) -> datetime:
    """Truncate microseconds to milliseconds and strip timezone info.

    MongoDB stores datetimes as naive UTC (millisecond precision). Stripping
    tzinfo here lets us compare the stored value directly against the
    timezone-aware input without a TypeError, because both sides become naive
    UTC after the round-trip.
    """
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000, tzinfo=None)


def make_response(
    identifier: EntityMentionIdentifier,
    cluster_id: str = "cluster-it-001",
    timestamp: datetime | None = None,
    ere_request_id: str = "req-it-001:001",
    n_candidates: int = 1,
) -> EntityMentionResolutionResponse:
    ts = timestamp or datetime.now(UTC)
    candidates = [make_cluster(cluster_id)] + [
        make_cluster(f"alt-{i}", conf=0.4, sim=0.35) for i in range(n_candidates - 1)
    ]
    return EntityMentionResolutionResponse(
        ere_request_id=ere_request_id,
        entity_mention_id=identifier,
        candidates=candidates,
        timestamp=ts,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def registry_service(mongo_db):
    resolution_repo = MongoResolutionRequestRepository(mongo_db)
    lookup_repo = MongoLookupStateRepository(mongo_db)
    return RequestRegistryService(
        resolution_repo=resolution_repo,
        lookup_repo=lookup_repo,
        hasher=SHA256ContentHasher(),
        rdf_config=None,
    )


@pytest.fixture()
def decision_service(mongo_db):
    return DecisionStoreService(repository=MongoDecisionRepository(mongo_db))


@pytest.fixture()
def integration_service(registry_service, decision_service):
    return OutcomeIntegrationService(
        registry_service=registry_service,
        decision_service=decision_service,
        on_outcome_stored=None,
    )


@pytest.fixture()
async def seeded_registry(mongo_db):
    """Pre-seed a resolution request for the default test triad."""
    repo = MongoResolutionRequestRepository(mongo_db)
    content = "@prefix org: <http://www.w3.org/ns/org#> ."
    record = ResolutionRequestRecord(
        identifiedBy=make_identifier(),
        content=content,
        content_type="text/turtle",
        content_hash=SHA256ContentHasher().hash(content),
        received_at=datetime.now(UTC),
    )
    await repo.store(record)
    return record


# ---------------------------------------------------------------------------
# IT-001: solicited outcome — Decision Store updated
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_it001_solicited_outcome_persisted(
    seeded_registry, integration_service, decision_service
):
    """IT-001: valid solicited outcome → Decision Store updated with cluster + timestamp."""
    identifier = make_identifier()
    response = make_response(identifier, cluster_id="cluster-org-42", n_candidates=2)

    await integration_service.integrate_outcome(response)

    stored = await decision_service.get_decision_by_triad(identifier)
    assert stored is not None
    assert stored.current_placement.cluster_id == "cluster-org-42"
    assert stored.updated_at == truncate_ms(response.timestamp)


# ---------------------------------------------------------------------------
# IT-002: unsolicited outcome (ereNotification: prefix) — same pipeline
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_it002_unsolicited_outcome_updates_decision_store(
    seeded_registry, integration_service, decision_service
):
    """IT-002: unsolicited outcome (ereNotification: prefix) → Decision Store updated."""
    identifier = make_identifier()
    response = make_response(
        identifier,
        cluster_id="cluster-recluster-99",
        ere_request_id="ereNotification:rebuild-001",
    )

    await integration_service.integrate_outcome(response)

    stored = await decision_service.get_decision_by_triad(identifier)
    assert stored is not None
    assert stored.current_placement.cluster_id == "cluster-recluster-99"


# ---------------------------------------------------------------------------
# IT-003: duplicate outcome — only first persisted
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_it003_duplicate_outcome_rejected(
    seeded_registry, integration_service, decision_service
):
    """IT-003: same outcome sent twice → Decision Store unchanged after second call."""
    identifier = make_identifier()
    ts = datetime.now(UTC)
    response = make_response(identifier, cluster_id="cluster-dup", timestamp=ts)

    await integration_service.integrate_outcome(response)
    await integration_service.integrate_outcome(response)  # duplicate — rejected silently

    stored = await decision_service.get_decision_by_triad(identifier)
    assert stored is not None
    assert stored.current_placement.cluster_id == "cluster-dup"
    assert stored.updated_at == truncate_ms(ts)


# ---------------------------------------------------------------------------
# IT-004: late arrival — newer outcome wins, older rejected
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_it004_late_arrival_rejected(
    seeded_registry, integration_service, decision_service
):
    """IT-004: newer outcome accepted; late arrival (older timestamp) rejected."""
    identifier = make_identifier()
    t0 = datetime.now(UTC)
    t1_plus_1 = t0 + timedelta(seconds=10)

    newer = make_response(identifier, cluster_id="cluster-newer", timestamp=t1_plus_1)
    older = make_response(identifier, cluster_id="cluster-stale", timestamp=t0)

    await integration_service.integrate_outcome(newer)
    await integration_service.integrate_outcome(older)  # stale — rejected

    stored = await decision_service.get_decision_by_triad(identifier)
    assert stored is not None
    assert stored.current_placement.cluster_id == "cluster-newer"
    assert stored.updated_at == truncate_ms(t1_plus_1)
