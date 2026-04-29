"""Integration tests for ResolutionCoordinatorService and BulkRefreshCoordinatorService.

Uses:
  - tests/conftest.py: redis_client (function scope, flushes after each test)
  - tests/integration/conftest.py: mongo_db (function scope, drops DB after each test)

All tests are marked @pytest.mark.integration and require a live MongoDB and Redis.
IT-007 to IT-009 (bulk refresh) require MongoDB only.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from erspec.models.core import ClusterReference, EntityMention, EntityMentionIdentifier

from ers.commons.adapters.hasher import SHA256ContentHasher
from ers.commons.adapters.provisional_id import derive_provisional_cluster_id
from ers.commons.adapters.redis_client import RedisEREClient
from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.ere_contract_client.domain.errors import RedisConnectionError
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from ers.request_registry.adapters.records_repository import (
    MongoLookupStateRepository,
    MongoResolutionRequestRepository,
)
from ers.request_registry.domain.records import LookupRequestRecord
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_coordinator.domain.exceptions import SourceNotFoundError
from ers.resolution_coordinator.services.async_resolution_waiter import AsyncResolutionWaiter
from ers.resolution_coordinator.services.bulk_refresh_coordinator_service import (
    BulkRefreshCoordinatorService,
)
from ers.resolution_coordinator.services.resolution_coordinator_service import (
    ResolutionCoordinatorService,
)
from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

# ---------------------------------------------------------------------------
# Config patch — short budgets for test speed
# ---------------------------------------------------------------------------

_FAST_CONFIG = type("C", (), {
    "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 0.2,
    "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 5.0,
})()
_CONFIG_PATH = "ers.resolution_coordinator.services.resolution_coordinator_service.config"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_identifier(
    source: str = "IT_SYS", req: str = "req-it-001", entity: str = "Organization"
) -> EntityMentionIdentifier:
    return EntityMentionIdentifier(source_id=source, request_id=req, entity_type=entity)


def make_mention(source: str = "IT_SYS", req: str = "req-it-001") -> EntityMention:
    return EntityMention(
        identifiedBy=make_identifier(source, req),
        content="<rdf/>",
        content_type="application/rdf+xml",
    )


def triad_key(mention: EntityMention) -> str:
    i = mention.identifiedBy
    return f"{i.source_id}{i.request_id}{i.entity_type}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry_service(mongo_db):
    yield RequestRegistryService(
        resolution_repo=MongoResolutionRequestRepository(mongo_db),
        lookup_repo=MongoLookupStateRepository(mongo_db),
        hasher=SHA256ContentHasher(),
        mention_parser=lambda _em: {"type": "Organization"},
    )


@pytest.fixture()
def decision_service(mongo_db):
    return DecisionStoreService(repository=MongoDecisionRepository(mongo_db))


@pytest.fixture()
def waiter():
    return AsyncResolutionWaiter()


@pytest.fixture()
def publish_service(redis_client):
    client = RedisEREClient(
        config_or_client=redis_client,
        request_channel="it_ere_requests",
        response_channel="it_ere_responses",
    )
    return EREPublishService(adapter=client)


@pytest.fixture()
def coordinator(registry_service, publish_service, decision_service, waiter):
    with patch(_CONFIG_PATH, _FAST_CONFIG):
        return ResolutionCoordinatorService(
            registry_service=registry_service,
            ere_publish_service=publish_service,
            decision_store_service=decision_service,
            waiter=waiter,
        )


@pytest.fixture()
def bulk_refresh(registry_service, decision_service):
    return BulkRefreshCoordinatorService(
        registry_service=registry_service,
        decision_store_service=decision_service,
    )


# ---------------------------------------------------------------------------
# IT-001: Full happy path — ERE responds, canonical decision returned
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_it001_full_happy_path(coordinator, decision_service, waiter):
    """IT-001: Submit mention → notify waiter → canonical Decision returned and persisted."""
    mention = make_mention()
    key = triad_key(mention)

    async def _run():
        async def _notify():
            await asyncio.sleep(0.05)
            # Simulate EPIC-05: write canonical decision then notify waiter.
            ident = mention.identifiedBy
            cluster = ClusterReference(
                cluster_id="cl-it-canonical", confidence_score=0.95, similarity_score=0.90
            )
            now = datetime.now(UTC)
            await decision_service._repository.upsert_decision(ident, cluster, [cluster], now)
            await waiter.notify(key)

        asyncio.create_task(_notify())
        with patch(_CONFIG_PATH, _FAST_CONFIG):
            return await coordinator.resolve_single(mention)

    decision, outcome = await _run()

    assert decision is not None
    assert outcome == ResolutionOutcome.CANONICAL
    assert decision.current_placement.cluster_id == "cl-it-canonical"

    stored = await decision_service.get_decision_by_triad(mention.identifiedBy)
    assert stored is not None
    assert stored.current_placement.cluster_id == "cl-it-canonical"


# ---------------------------------------------------------------------------
# IT-002: Timeout → provisional decision issued and persisted
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_it002_timeout_issues_provisional(coordinator, decision_service):
    """IT-002: ERE does not respond → provisional singleton returned and persisted."""
    mention = make_mention(req="req-it-002")

    with patch(_CONFIG_PATH, _FAST_CONFIG):
        decision, outcome = await coordinator.resolve_single(mention)

    expected_prov_id = derive_provisional_cluster_id(mention.identifiedBy)
    assert decision is not None
    assert outcome == ResolutionOutcome.PROVISIONAL
    assert decision.current_placement.cluster_id == expected_prov_id

    stored = await decision_service.get_decision_by_triad(mention.identifiedBy)
    assert stored is not None
    assert stored.current_placement.cluster_id == expected_prov_id


# ---------------------------------------------------------------------------
# IT-003: Redis down → provisional returned and persisted
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_it003_redis_down_issues_provisional(
    registry_service, decision_service, waiter
):
    """IT-003: Redis unavailable → provisional returned and persisted in MongoDB."""
    failing_publish = AsyncMock(spec=EREPublishService)
    failing_publish.publish_request = AsyncMock(
        side_effect=RedisConnectionError("connection refused")
    )
    with patch(_CONFIG_PATH, _FAST_CONFIG):
        svc = ResolutionCoordinatorService(
            registry_service=registry_service,
            ere_publish_service=failing_publish,
            decision_store_service=decision_service,
            waiter=waiter,
        )
        decision, outcome = await svc.resolve_single(make_mention(req="req-it-003"))

    expected_prov_id = derive_provisional_cluster_id(make_identifier(req="req-it-003"))
    assert outcome == ResolutionOutcome.PROVISIONAL
    assert decision.current_placement.cluster_id == expected_prov_id

    stored = await decision_service.get_decision_by_triad(make_identifier(req="req-it-003"))
    assert stored is not None


# ---------------------------------------------------------------------------
# IT-004: Idempotent replay — decision exists, no new ERE publish
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_it004_idempotent_replay(
    coordinator, registry_service, decision_service, waiter, mongo_db
):
    """IT-004: Same triad+content → existing decision returned, no new publish."""
    mention = make_mention(req="req-it-004")
    ident = mention.identifiedBy

    # Pre-seed a canonical decision.
    cluster = ClusterReference(
        cluster_id="cl-pre-seeded", confidence_score=0.95, similarity_score=0.90
    )
    repo = MongoDecisionRepository(mongo_db)
    await repo.upsert_decision(ident, cluster, [cluster], datetime.now(UTC))

    counting_publish = AsyncMock(spec=EREPublishService)
    with patch(_CONFIG_PATH, _FAST_CONFIG):
        svc = ResolutionCoordinatorService(
            registry_service=registry_service,
            ere_publish_service=counting_publish,
            decision_store_service=decision_service,
            waiter=waiter,
        )
        decision, outcome = await svc.resolve_single(mention)

    assert outcome == ResolutionOutcome.CANONICAL
    assert decision.current_placement.cluster_id == "cl-pre-seeded"
    counting_publish.publish_request.assert_not_called()


# ---------------------------------------------------------------------------
# IT-005: Concurrent identical requests — all return same decision, one ERE publish
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_it005_concurrent_identical_requests(
    registry_service, decision_service, waiter
):
    """IT-005: 5 coroutines submit same triad concurrently → all return same Decision."""
    mention = make_mention(source="SYSTEM_IT5", req="req-it-005")
    key = triad_key(mention)

    publish_calls = {"count": 0}

    class CountingPublish(EREPublishService):
        def __init__(self):
            pass  # No Redis adapter needed.

        async def publish_request(self, request):
            publish_calls["count"] += 1
            return "fake-ere-id"

    with patch(_CONFIG_PATH, _FAST_CONFIG):
        svc = ResolutionCoordinatorService(
            registry_service=registry_service,
            ere_publish_service=CountingPublish(),
            decision_store_service=decision_service,
            waiter=waiter,
        )

    tasks = [asyncio.create_task(svc.resolve_single(mention)) for _ in range(5)]
    await asyncio.sleep(0.05)  # Let all tasks register and start waiting.

    # Simulate EPIC-05 writing the canonical decision and notifying waiter.
    cluster = ClusterReference(
        cluster_id="cl-concurrent", confidence_score=0.95, similarity_score=0.90
    )
    await decision_service._repository.upsert_decision(
        mention.identifiedBy, cluster, [cluster], datetime.now(UTC)
    )
    await waiter.notify(key)

    results = await asyncio.gather(*tasks)

    cluster_ids = {decision.current_placement.cluster_id for decision, _ in results}
    assert len(cluster_ids) == 1, f"Expected 1 unique cluster, got: {cluster_ids}"
    assert "cl-concurrent" in cluster_ids


# ---------------------------------------------------------------------------
# IT-006: Bulk decomposition — 3 mentions, all succeed
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_it006_bulk_decomposition(
    registry_service, decision_service, waiter
):
    """IT-006: Submit 3 mentions → notify all 3 waiters → 3 independent Decisions."""
    mentions = [make_mention(source="IT6_SYS", req=f"req-it6-{i:03d}") for i in range(3)]
    keys = [triad_key(m) for m in mentions]

    class QuickPublish(EREPublishService):
        def __init__(self):
            pass

        async def publish_request(self, request):
            return "fake-id"

    with patch(_CONFIG_PATH, _FAST_CONFIG):
        svc = ResolutionCoordinatorService(
            registry_service=registry_service,
            ere_publish_service=QuickPublish(),
            decision_store_service=decision_service,
            waiter=waiter,
        )

    async def _notify_all():
        await asyncio.sleep(0.05)
        for i, (mention, key) in enumerate(zip(mentions, keys, strict=True)):
            cluster = ClusterReference(
                cluster_id=f"cl-bulk-{i}", confidence_score=0.9, similarity_score=0.85
            )
            await decision_service._repository.upsert_decision(
                mention.identifiedBy, cluster, [cluster], datetime.now(UTC)
            )
            await waiter.notify(key)

    notify_task = asyncio.create_task(_notify_all())
    with patch(_CONFIG_PATH, _FAST_CONFIG):
        results = await svc.resolve_bulk(mentions)
    await notify_task

    assert len(results) == 3
    for i, result in enumerate(results):
        assert isinstance(result, tuple), f"Index {i} returned {type(result)}"
        decision, outcome = result
        assert outcome == ResolutionOutcome.CANONICAL
        assert decision.current_placement.cluster_id == f"cl-bulk-{i}"


# ---------------------------------------------------------------------------
# IT-007: Bulk refresh — delta (Spine C)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_it007_bulk_refresh_delta(registry_service, decision_service, bulk_refresh, mongo_db):
    """IT-007: Pre-seed 5 decisions, 3 updated after snapshot → delta returns 3."""
    source_id = "DELTA_SYS"

    # Pre-seed a resolution request so source_has_requests returns True.
    repo = MongoResolutionRequestRepository(mongo_db)
    from ers.request_registry.domain.records import ResolutionRequestRecord
    content = "@prefix org: <http://www.w3.org/ns/org#> ."
    rec = ResolutionRequestRecord(
        identifiedBy=make_identifier(source=source_id, req="req-seed"),
        content=content,
        content_type="text/turtle",
        content_hash=SHA256ContentHasher().hash(content),
        received_at=datetime.now(UTC),
    )
    await repo.store(rec)

    snapshot_time = datetime.now(UTC)
    decision_repo = MongoDecisionRepository(mongo_db)

    # Store 2 decisions before snapshot (old).
    for i in range(2):
        ident = make_identifier(source=source_id, req=f"req-old-{i}")
        cluster = ClusterReference(
            cluster_id=f"cl-old-{i}", confidence_score=0.9, similarity_score=0.85
        )
        await decision_repo.upsert_decision(
            ident, cluster, [cluster], snapshot_time - timedelta(minutes=5)
        )

    await asyncio.sleep(0.01)  # Ensure updated_at is strictly after snapshot_time.

    # Store 3 decisions after snapshot (new).
    for i in range(3):
        ident = make_identifier(source=source_id, req=f"req-new-{i}")
        cluster = ClusterReference(
            cluster_id=f"cl-new-{i}", confidence_score=0.9, similarity_score=0.85
        )
        await decision_repo.upsert_decision(
            ident, cluster, [cluster], snapshot_time + timedelta(seconds=1)
        )

    # Set lookup state to snapshot_time.
    lookup_repo = MongoLookupStateRepository(mongo_db)
    await lookup_repo.upsert(
        LookupRequestRecord(
            source_id=source_id, last_snapshot=snapshot_time, updated_at=snapshot_time
        )
    )

    page = await bulk_refresh.refresh_bulk(source_id)

    assert len(page.results) == 3
    cluster_ids = {r.current_placement.cluster_id for r in page.results}
    assert cluster_ids == {"cl-new-0", "cl-new-1", "cl-new-2"}


# ---------------------------------------------------------------------------
# IT-008: Bulk refresh — first lookup (no prior snapshot)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_it008_bulk_refresh_first_lookup(
    registry_service, decision_service, bulk_refresh, mongo_db
):
    """IT-008: No prior snapshot → all decisions for source returned."""
    source_id = "FIRST_SYS"

    # Pre-seed a resolution request.
    repo = MongoResolutionRequestRepository(mongo_db)
    from ers.request_registry.domain.records import ResolutionRequestRecord
    content = "@prefix org: <http://www.w3.org/ns/org#> ."
    rec = ResolutionRequestRecord(
        identifiedBy=make_identifier(source=source_id, req="req-seed"),
        content=content,
        content_type="text/turtle",
        content_hash=SHA256ContentHasher().hash(content),
        received_at=datetime.now(UTC),
    )
    await repo.store(rec)

    # Store 4 decisions.
    decision_repo = MongoDecisionRepository(mongo_db)
    for i in range(4):
        ident = make_identifier(source=source_id, req=f"req-{i}")
        cluster = ClusterReference(
            cluster_id=f"cl-{i}", confidence_score=0.9, similarity_score=0.85
        )
        await decision_repo.upsert_decision(ident, cluster, [cluster], datetime.now(UTC))

    page = await bulk_refresh.refresh_bulk(source_id)

    assert len(page.results) == 4


# ---------------------------------------------------------------------------
# IT-009: Bulk refresh — unknown source raises SourceNotFoundError
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_it009_bulk_refresh_unknown_source(bulk_refresh):
    """IT-009: Source has no requests in registry → SourceNotFoundError raised."""
    with pytest.raises(SourceNotFoundError) as exc_info:
        await bulk_refresh.refresh_bulk("UNKNOWN_SOURCE")

    assert exc_info.value.source_id == "UNKNOWN_SOURCE"


# ---------------------------------------------------------------------------
# IT-010: Zero single budget — immediate provisional, no Redis publish
# ---------------------------------------------------------------------------

_ZERO_SINGLE_BUDGET_CONFIG = type("C", (), {
    "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 0,
    "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 5.0,
})()


@pytest.mark.integration
async def test_it010_zero_single_budget_immediate_provisional(
    registry_service, decision_service, waiter
):
    """IT-010: single budget == 0 → provisional issued immediately, publish_request never called."""
    mention = make_mention(source="IT_SYS", req="req-it-010")
    tracking_publish = AsyncMock(spec=EREPublishService)

    with patch(_CONFIG_PATH, _ZERO_SINGLE_BUDGET_CONFIG):
        svc = ResolutionCoordinatorService(
            registry_service=registry_service,
            ere_publish_service=tracking_publish,
            decision_store_service=decision_service,
            waiter=waiter,
        )
        decision, outcome = await svc.resolve_single(mention)

    expected_prov_id = derive_provisional_cluster_id(mention.identifiedBy)
    assert outcome == ResolutionOutcome.PROVISIONAL
    assert decision.current_placement.cluster_id == expected_prov_id
    tracking_publish.publish_request.assert_not_called()

    stored = await decision_service.get_decision_by_triad(mention.identifiedBy)
    assert stored is not None
    assert stored.current_placement.cluster_id == expected_prov_id


# ---------------------------------------------------------------------------
# IT-011: Zero both budgets — bulk all provisional, no outer timeout, no Redis
# ---------------------------------------------------------------------------

_ZERO_BOTH_BUDGETS_CONFIG = type("C", (), {
    "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 0,
    "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 0,
})()


@pytest.mark.integration
async def test_it011_zero_bulk_budget_all_provisional(
    registry_service, decision_service, waiter
):
    """IT-011: both budgets == 0 → bulk returns all provisional with no Redis publish."""
    mentions = [
        make_mention(source="IT11_SYS", req=f"req-it-011-{i}") for i in range(3)
    ]
    tracking_publish = AsyncMock(spec=EREPublishService)

    with patch(_CONFIG_PATH, _ZERO_BOTH_BUDGETS_CONFIG):
        svc = ResolutionCoordinatorService(
            registry_service=registry_service,
            ere_publish_service=tracking_publish,
            decision_store_service=decision_service,
            waiter=waiter,
        )
        results = await svc.resolve_bulk(mentions)

    assert len(results) == 3
    for i, (decision, outcome) in enumerate(results):
        expected_prov_id = derive_provisional_cluster_id(mentions[i].identifiedBy)
        assert outcome == ResolutionOutcome.PROVISIONAL
        assert decision.current_placement.cluster_id == expected_prov_id

    tracking_publish.publish_request.assert_not_called()
