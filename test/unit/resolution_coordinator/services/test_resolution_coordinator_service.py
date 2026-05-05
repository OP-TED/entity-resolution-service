"""Unit tests for ResolutionCoordinatorService.

asyncio_mode = auto (pytest.ini) — no @pytest.mark.asyncio decorator needed.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from erspec.models.core import (
    ClusterReference,
    Decision,
    EntityMention,
    EntityMentionIdentifier,
)

from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.commons.services.exceptions import ServiceUnavailableError
from ers.ere_contract_client.domain.errors import (
    ChannelUnavailableError,
    RedisConnectionError,
)
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from ers.rdf_mention_parser.domain.exceptions import MalformedRDFError
from ers.request_registry.domain.errors import (
    RepositoryConnectionError as RegistryConnectionError,
)
from ers.request_registry.services.exceptions import IdempotencyConflictError
from ers.request_registry.services.request_registry_service import (
    RequestRegistryService,
)
from ers.resolution_coordinator.domain.exceptions import (
    ParsingFailedError,
    ResolutionTimeoutError,
)
from ers.resolution_coordinator.services.async_resolution_waiter import (
    AsyncResolutionWaiter,
)
from ers.resolution_coordinator.services.resolution_coordinator_service import (
    ResolutionCoordinatorService,
)
from ers.resolution_decision_store.domain.errors import (
    RepositoryConnectionError,
    StaleOutcomeError,
)
from ers.resolution_decision_store.services.decision_store_service import (
    DecisionStoreService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_identifier(
    source="SRC", req="req-001", entity="Organization"
) -> EntityMentionIdentifier:
    return EntityMentionIdentifier(
        source_id=source, request_id=req, entity_type=entity
    )


def make_entity_mention(
    source="SRC", req="req-001", entity="Organization"
) -> EntityMention:
    return EntityMention(
        identifiedBy=make_identifier(source, req, entity),
        content="<rdf/>",
        content_type="application/rdf+xml",
    )


def make_decision(cluster_id="cl-001") -> Decision:
    now = datetime.now(UTC)
    ident = make_identifier()
    return Decision(
        id="decision-id",
        about_entity_mention=ident,
        current_placement=ClusterReference(
            cluster_id=cluster_id,
            confidence_score=0.9,
            similarity_score=0.85,
        ),
        candidates=[
            ClusterReference(
                cluster_id=cluster_id,
                confidence_score=0.9,
                similarity_score=0.85,
            )
        ],
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry_svc():
    return AsyncMock(spec=RequestRegistryService)


@pytest.fixture
def publish_svc():
    return AsyncMock(spec=EREPublishService)


@pytest.fixture
def decision_svc():
    return AsyncMock(spec=DecisionStoreService)


@pytest.fixture
def waiter():
    return AsyncMock(spec=AsyncResolutionWaiter)


@pytest.fixture
def coordinator(registry_svc, publish_svc, decision_svc, waiter):
    return ResolutionCoordinatorService(
        registry_svc, publish_svc, decision_svc, waiter
    )


# ---------------------------------------------------------------------------
# TC-001: __init__ validation
# ---------------------------------------------------------------------------

class TestInitValidation:
    def test_rejects_negative_single_budget(self, monkeypatch, registry_svc, publish_svc, decision_svc, waiter):
        monkeypatch.setattr(
            "ers.resolution_coordinator.services.resolution_coordinator_service.config",
            type("C", (), {
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": -1,
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 120.0,
            })(),
        )
        with pytest.raises(ValueError, match="SINGLE_REQUEST_TIME_BUDGET"):
            ResolutionCoordinatorService(registry_svc, publish_svc, decision_svc, waiter)

    def test_rejects_negative_bulk_budget(self, monkeypatch, registry_svc, publish_svc, decision_svc, waiter):
        monkeypatch.setattr(
            "ers.resolution_coordinator.services.resolution_coordinator_service.config",
            type("C", (), {
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 30.0,
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": -1,
            })(),
        )
        with pytest.raises(ValueError, match="BULK_REQUEST_TIME_BUDGET"):
            ResolutionCoordinatorService(registry_svc, publish_svc, decision_svc, waiter)


# ---------------------------------------------------------------------------
# TC-002: Happy path — ERE responds in time
# ---------------------------------------------------------------------------

class TestResolveSingleHappyPath:
    async def test_ere_responds_returns_canonical_decision(
        self, registry_svc, publish_svc, decision_svc
    ):
        real_waiter = AsyncResolutionWaiter()
        svc = ResolutionCoordinatorService(
            registry_svc, publish_svc, decision_svc, real_waiter
        )
        triad_key = "SRCreq-001Organization"

        ere_decision = make_decision(cluster_id="cl-canonical")
        decision_svc.get_decision_by_triad.side_effect = [None, ere_decision]

        async def signal_ere():
            await asyncio.sleep(0.02)
            await real_waiter.notify(triad_key)

        asyncio.create_task(signal_ere())
        decision, outcome = await svc.resolve_single(make_entity_mention())
        assert decision.current_placement.cluster_id == "cl-canonical"
        assert outcome == ResolutionOutcome.CANONICAL
        publish_svc.publish_request.assert_called_once()


# ---------------------------------------------------------------------------
# TC-003: ERE timeout → provisional
# ---------------------------------------------------------------------------

class TestResolveSingleTimeout:
    async def test_ere_timeout_issues_provisional(
        self, monkeypatch, registry_svc, publish_svc, decision_svc
    ):
        monkeypatch.setattr(
            "ers.resolution_coordinator.services.resolution_coordinator_service.config",
            type("C", (), {
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 0.05,
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 120.0,
            })(),
        )
        real_waiter = AsyncResolutionWaiter()
        svc = ResolutionCoordinatorService(
            registry_svc, publish_svc, decision_svc, real_waiter
        )

        decision_svc.get_decision_by_triad.return_value = None
        provisional_decision = make_decision(cluster_id="provisional-hash")
        decision_svc.store_decision.return_value = provisional_decision

        decision, outcome = await svc.resolve_single(make_entity_mention())
        assert decision.current_placement.cluster_id == "provisional-hash"
        assert outcome == ResolutionOutcome.PROVISIONAL
        decision_svc.store_decision.assert_called_once()


# ---------------------------------------------------------------------------
# TC-004 / TC-004b: Redis / Channel down → provisional
# ---------------------------------------------------------------------------

class TestResolveSinglePublishFailure:
    async def test_redis_connection_error_raises_service_unavailable(
        self, coordinator, publish_svc, decision_svc, waiter
    ):
        decision_svc.get_decision_by_triad.return_value = None
        publish_svc.publish_request.side_effect = RedisConnectionError("conn refused")

        with pytest.raises(ServiceUnavailableError):
            await coordinator.resolve_single(make_entity_mention())
        decision_svc.store_decision.assert_not_called()

    async def test_channel_unavailable_raises_service_unavailable(
        self, coordinator, publish_svc, decision_svc, waiter
    ):
        decision_svc.get_decision_by_triad.return_value = None
        publish_svc.publish_request.side_effect = ChannelUnavailableError("no subscribers")

        with pytest.raises(ServiceUnavailableError):
            await coordinator.resolve_single(make_entity_mention())


# ---------------------------------------------------------------------------
# TC-005: Idempotent — decision exists
# ---------------------------------------------------------------------------

class TestResolveSingleIdempotent:
    async def test_existing_decision_returned_immediately(
        self, coordinator, decision_svc, publish_svc, waiter
    ):
        existing = make_decision(cluster_id="cl-existing")
        decision_svc.get_decision_by_triad.return_value = existing

        decision, outcome = await coordinator.resolve_single(make_entity_mention())
        assert decision.current_placement.cluster_id == "cl-existing"
        assert outcome == ResolutionOutcome.CANONICAL
        publish_svc.publish_request.assert_not_called()
        waiter.get_or_create.assert_not_called()

    async def test_no_decision_yet_publishes_and_waits(
        self, coordinator, decision_svc, publish_svc, waiter
    ):
        canonical = make_decision(cluster_id="cl-canonical")
        decision_svc.get_decision_by_triad.side_effect = [None, canonical]
        waiter.get_or_create.return_value = asyncio.Event()
        # Event is already not set but the mock's return is an Event we set immediately
        event = waiter.get_or_create.return_value
        event.set()

        decision, outcome = await coordinator.resolve_single(make_entity_mention())
        assert decision.current_placement.cluster_id == "cl-canonical"
        assert outcome == ResolutionOutcome.CANONICAL
        publish_svc.publish_request.assert_called_once()


# ---------------------------------------------------------------------------
# TC-007: Idempotency conflict
# ---------------------------------------------------------------------------

class TestResolveSingleIdempotencyConflict:
    async def test_conflict_propagates(
        self, coordinator, registry_svc, decision_svc
    ):
        ident = make_identifier()
        registry_svc.register_resolution_request.side_effect = (
            IdempotencyConflictError(ident)
        )
        with pytest.raises(IdempotencyConflictError):
            await coordinator.resolve_single(make_entity_mention())
        decision_svc.store_decision.assert_not_called()


# ---------------------------------------------------------------------------
# TC-008 / TC-009: Parse failures
# ---------------------------------------------------------------------------

class TestResolveSingleParseFailure:
    async def test_malformed_rdf_raises_parsing_failed(
        self, coordinator, registry_svc, publish_svc
    ):
        registry_svc.register_resolution_request.side_effect = MalformedRDFError(
            "application/rdf+xml"
        )
        with pytest.raises(ParsingFailedError) as exc_info:
            await coordinator.resolve_single(make_entity_mention())
        assert isinstance(exc_info.value.cause, MalformedRDFError)
        publish_svc.publish_request.assert_not_called()

    async def test_empty_content_raises_parsing_failed(
        self, coordinator, registry_svc
    ):
        registry_svc.register_resolution_request.side_effect = ValueError(
            "content must not be empty"
        )
        with pytest.raises(ParsingFailedError) as exc_info:
            await coordinator.resolve_single(make_entity_mention())
        assert isinstance(exc_info.value.cause, ValueError)


# ---------------------------------------------------------------------------
# TC-010: Decision Store unavailable on provisional write
# ---------------------------------------------------------------------------

class TestResolveSingleDecisionStoreDown:
    async def test_repo_connection_error_raises_service_unavailable(
        self, monkeypatch, registry_svc, publish_svc, decision_svc
    ):
        monkeypatch.setattr(
            "ers.resolution_coordinator.services.resolution_coordinator_service.config",
            type("C", (), {
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 0.05,
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 120.0,
            })(),
        )
        real_waiter = AsyncResolutionWaiter()
        svc = ResolutionCoordinatorService(registry_svc, publish_svc, decision_svc, real_waiter)
        decision_svc.get_decision_by_triad.return_value = None
        decision_svc.store_decision.side_effect = RepositoryConnectionError("MongoDB down")

        with pytest.raises(ServiceUnavailableError):
            await svc.resolve_single(make_entity_mention())


# ---------------------------------------------------------------------------
# TC-011: Stale provisional write
# ---------------------------------------------------------------------------

class TestResolveSingleStaleOutcome:
    async def test_stale_returns_existing_decision(
        self, monkeypatch, registry_svc, publish_svc, decision_svc
    ):
        """ERE wins the race (StaleOutcomeError) after ERE timeout — returns CANONICAL."""
        monkeypatch.setattr(
            "ers.resolution_coordinator.services.resolution_coordinator_service.config",
            type("C", (), {
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 0.05,
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 120.0,
            })(),
        )
        real_waiter = AsyncResolutionWaiter()
        svc = ResolutionCoordinatorService(
            registry_svc, publish_svc, decision_svc, real_waiter
        )
        decision_svc.get_decision_by_triad.side_effect = [
            None,  # initial check
            make_decision(cluster_id="cl-ere-winner"),  # after StaleOutcomeError
        ]
        decision_svc.store_decision.side_effect = StaleOutcomeError(
            "SRC", "req-001", "Organization", "2026-01-01", "2025-12-31"
        )

        decision, outcome = await svc.resolve_single(make_entity_mention())
        assert decision.current_placement.cluster_id == "cl-ere-winner"
        assert outcome == ResolutionOutcome.CANONICAL


# ---------------------------------------------------------------------------
# TC-012–015: Bulk resolution
# ---------------------------------------------------------------------------

class TestResolveBulk:
    async def test_all_succeed(
        self, coordinator, registry_svc, decision_svc, waiter
    ):
        mentions = [
            make_entity_mention("S", f"r{i}", "Org") for i in range(3)
        ]
        decisions = [make_decision(f"cl-{i}") for i in range(3)]

        decision_svc.get_decision_by_triad.side_effect = decisions

        results = await coordinator.resolve_bulk(mentions)
        assert len(results) == 3
        assert all(isinstance(r, tuple) for r in results)
        assert all(outcome == ResolutionOutcome.CANONICAL for _, outcome in results)

    async def test_partial_parse_failure(
        self, coordinator, registry_svc, decision_svc, waiter
    ):
        mentions = [make_entity_mention("S", f"r{i}", "Org") for i in range(3)]

        call_count = 0

        async def register_side_effect(mention):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise MalformedRDFError("application/rdf+xml")

        registry_svc.register_resolution_request.side_effect = register_side_effect
        decision_svc.get_decision_by_triad.return_value = make_decision("cl-ok")

        results = await coordinator.resolve_bulk(mentions)
        assert len(results) == 3
        assert isinstance(results[0], tuple)
        assert isinstance(results[1], ParsingFailedError)
        assert isinstance(results[2], tuple)

    async def test_empty_input(self, coordinator):
        results = await coordinator.resolve_bulk([])
        assert results == []

    async def test_bulk_budget_exceeded(
        self, monkeypatch, registry_svc, publish_svc, decision_svc
    ):
        monkeypatch.setattr(
            "ers.resolution_coordinator.services.resolution_coordinator_service.config",
            type("C", (), {
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 10.0,
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 0.05,
            })(),
        )
        real_waiter = AsyncResolutionWaiter()
        svc = ResolutionCoordinatorService(
            registry_svc, publish_svc, decision_svc, real_waiter
        )

        decision_svc.get_decision_by_triad.return_value = None

        mentions = [make_entity_mention("S", f"r{i}", "Org") for i in range(3)]
        with pytest.raises(ResolutionTimeoutError, match="Bulk resolution"):
            await svc.resolve_bulk(mentions)


# ---------------------------------------------------------------------------
# TC-016–019: Waiter lifecycle
# ---------------------------------------------------------------------------

class TestWaiterLifecycle:
    async def test_release_called_on_success(
        self, coordinator, decision_svc, waiter
    ):
        decision_svc.get_decision_by_triad.side_effect = [
            None,
            make_decision("cl-ok"),
        ]
        event = asyncio.Event()
        event.set()
        waiter.get_or_create.return_value = event

        await coordinator.resolve_single(make_entity_mention())
        waiter.release.assert_called_once()

    async def test_release_called_on_timeout(
        self, monkeypatch, registry_svc, publish_svc, decision_svc
    ):
        monkeypatch.setattr(
            "ers.resolution_coordinator.services.resolution_coordinator_service.config",
            type("C", (), {
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 0.02,
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 120.0,
            })(),
        )
        mock_waiter = AsyncMock(spec=AsyncResolutionWaiter)
        mock_waiter.get_or_create.return_value = asyncio.Event()
        svc = ResolutionCoordinatorService(
            registry_svc, publish_svc, decision_svc, mock_waiter
        )
        decision_svc.get_decision_by_triad.return_value = None
        decision_svc.store_decision.return_value = make_decision("prov")

        await svc.resolve_single(make_entity_mention())
        mock_waiter.release.assert_called_once()

    async def test_release_called_on_redis_failure(
        self, coordinator, publish_svc, decision_svc, waiter
    ):
        decision_svc.get_decision_by_triad.return_value = None
        publish_svc.publish_request.side_effect = RedisConnectionError("down")

        with pytest.raises(ServiceUnavailableError):
            await coordinator.resolve_single(make_entity_mention())
        waiter.release.assert_called_once()

    async def test_no_waiter_on_instant_decision(
        self, coordinator, decision_svc, waiter
    ):
        decision_svc.get_decision_by_triad.return_value = make_decision("cl-x")

        await coordinator.resolve_single(make_entity_mention())
        waiter.get_or_create.assert_not_called()


# ---------------------------------------------------------------------------
# lookup_by_triad
# ---------------------------------------------------------------------------

class TestLookupByTriad:
    async def test_returns_decision_when_found(
        self, coordinator, decision_svc
    ):
        expected = make_decision("cl-lookup")
        decision_svc.get_decision_by_triad.return_value = expected

        result = await coordinator.lookup_by_triad(make_identifier())

        assert result is expected
        decision_svc.get_decision_by_triad.assert_awaited_once_with(make_identifier())

    async def test_returns_none_when_not_found(
        self, coordinator, decision_svc
    ):
        decision_svc.get_decision_by_triad.return_value = None

        result = await coordinator.lookup_by_triad(make_identifier())

        assert result is None


# ---------------------------------------------------------------------------
# TC-IMM: Immediate provisional mode — single budget == 0
# ---------------------------------------------------------------------------

class TestImmediateProvisionalMode:
    """When ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET == 0, resolve_single skips ERE."""

    @pytest.fixture
    def zero_single_svc(self, monkeypatch, registry_svc, publish_svc, decision_svc):
        monkeypatch.setattr(
            "ers.resolution_coordinator.services.resolution_coordinator_service.config",
            type("C", (), {
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 0,
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 120.0,
            })(),
        )
        return ResolutionCoordinatorService(
            registry_svc, publish_svc, decision_svc, AsyncResolutionWaiter()
        )

    async def test_zero_single_budget_accepted_in_constructor(
        self, zero_single_svc
    ):
        """budget == 0 must NOT raise ValueError at construction time."""
        assert zero_single_svc is not None

    async def test_zero_single_budget_returns_provisional_immediately(
        self, zero_single_svc, publish_svc, decision_svc
    ):
        decision_svc.get_decision_by_triad.return_value = None
        provisional = make_decision(cluster_id="prov-instant")
        decision_svc.store_decision.return_value = provisional

        decision, outcome = await zero_single_svc.resolve_single(make_entity_mention())

        assert outcome == ResolutionOutcome.PROVISIONAL
        assert decision.current_placement.cluster_id == "prov-instant"
        publish_svc.publish_request.assert_not_called()

    async def test_zero_single_budget_skips_waiter(
        self, zero_single_svc, publish_svc, decision_svc
    ):
        decision_svc.get_decision_by_triad.return_value = None
        decision_svc.store_decision.return_value = make_decision(cluster_id="prov-x")

        await zero_single_svc.resolve_single(make_entity_mention())

        publish_svc.publish_request.assert_not_called()

    async def test_zero_single_budget_still_returns_existing_decision(
        self, zero_single_svc, decision_svc, publish_svc
    ):
        """Idempotent replay takes priority even in zero-budget mode."""
        existing = make_decision(cluster_id="cl-existing")
        decision_svc.get_decision_by_triad.return_value = existing

        decision, outcome = await zero_single_svc.resolve_single(make_entity_mention())

        assert outcome == ResolutionOutcome.CANONICAL
        assert decision.current_placement.cluster_id == "cl-existing"
        publish_svc.publish_request.assert_not_called()


# ---------------------------------------------------------------------------
# TC-BULK0: Zero bulk budget — no outer asyncio.wait_for timeout
# ---------------------------------------------------------------------------

class TestZeroBulkBudget:
    """When ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET == 0, resolve_bulk runs without outer timeout."""

    @pytest.fixture
    def zero_bulk_svc(self, monkeypatch, registry_svc, publish_svc, decision_svc):
        monkeypatch.setattr(
            "ers.resolution_coordinator.services.resolution_coordinator_service.config",
            type("C", (), {
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 0,
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 0,
            })(),
        )
        return ResolutionCoordinatorService(
            registry_svc, publish_svc, decision_svc, AsyncResolutionWaiter()
        )

    async def test_zero_bulk_budget_accepted_in_constructor(
        self, zero_bulk_svc
    ):
        """bulk_budget == 0 must NOT raise ValueError at construction time."""
        assert zero_bulk_svc is not None

    async def test_zero_bulk_budget_returns_all_provisional(
        self, zero_bulk_svc, decision_svc, publish_svc
    ):
        """With both budgets == 0, bulk returns provisional for every mention."""
        mentions = [make_entity_mention("S", f"r{i}", "Organization") for i in range(3)]
        provisionals = [make_decision(cluster_id=f"prov-{i}") for i in range(3)]

        decision_svc.get_decision_by_triad.return_value = None
        decision_svc.store_decision.side_effect = provisionals

        results = await zero_bulk_svc.resolve_bulk(mentions)

        assert len(results) == 3
        assert all(outcome == ResolutionOutcome.PROVISIONAL for _, outcome in results)
        publish_svc.publish_request.assert_not_called()


# ---------------------------------------------------------------------------
# TC-SU: ServiceUnavailableError on MongoDB / Redis connection failures
# ---------------------------------------------------------------------------

class TestResolveSingleServiceUnavailable:
    async def test_mongo_down_at_registration_raises_service_unavailable(
        self, coordinator, registry_svc
    ):
        registry_svc.register_resolution_request.side_effect = RegistryConnectionError(
            "timeout"
        )

        with pytest.raises(ServiceUnavailableError):
            await coordinator.resolve_single(make_entity_mention())

    async def test_redis_connection_error_on_publish_raises_service_unavailable(
        self, monkeypatch, registry_svc, publish_svc, decision_svc
    ):
        monkeypatch.setattr(
            "ers.resolution_coordinator.services.resolution_coordinator_service.config",
            type("C", (), {
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 30.0,
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 120.0,
            })(),
        )
        real_waiter = AsyncResolutionWaiter()
        svc = ResolutionCoordinatorService(registry_svc, publish_svc, decision_svc, real_waiter)
        decision_svc.get_decision_by_triad.return_value = None
        publish_svc.publish_request.side_effect = RedisConnectionError("refused")

        with pytest.raises(ServiceUnavailableError):
            await svc.resolve_single(make_entity_mention())

    async def test_channel_unavailable_on_publish_raises_service_unavailable(
        self, monkeypatch, registry_svc, publish_svc, decision_svc
    ):
        monkeypatch.setattr(
            "ers.resolution_coordinator.services.resolution_coordinator_service.config",
            type("C", (), {
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 30.0,
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 120.0,
            })(),
        )
        real_waiter = AsyncResolutionWaiter()
        svc = ResolutionCoordinatorService(registry_svc, publish_svc, decision_svc, real_waiter)
        decision_svc.get_decision_by_triad.return_value = None
        publish_svc.publish_request.side_effect = ChannelUnavailableError("channel full")

        with pytest.raises(ServiceUnavailableError):
            await svc.resolve_single(make_entity_mention())

    async def test_mongo_down_at_provisional_write_raises_service_unavailable(
        self, monkeypatch, registry_svc, publish_svc, decision_svc
    ):
        monkeypatch.setattr(
            "ers.resolution_coordinator.services.resolution_coordinator_service.config",
            type("C", (), {
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 0.05,
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 120.0,
            })(),
        )
        real_waiter = AsyncResolutionWaiter()
        svc = ResolutionCoordinatorService(registry_svc, publish_svc, decision_svc, real_waiter)
        decision_svc.get_decision_by_triad.return_value = None
        decision_svc.store_decision.side_effect = RepositoryConnectionError("Mongo down")

        with pytest.raises(ServiceUnavailableError):
            await svc.resolve_single(make_entity_mention())

    async def test_ere_timeout_still_issues_provisional(
        self, monkeypatch, registry_svc, publish_svc, decision_svc
    ):
        """ERE timeout (Redis fine, ERE silent) still falls back to provisional."""
        monkeypatch.setattr(
            "ers.resolution_coordinator.services.resolution_coordinator_service.config",
            type("C", (), {
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 0.05,
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 120.0,
            })(),
        )
        real_waiter = AsyncResolutionWaiter()
        svc = ResolutionCoordinatorService(registry_svc, publish_svc, decision_svc, real_waiter)
        decision_svc.get_decision_by_triad.return_value = None
        provisional = make_decision("prov-cl")
        decision_svc.store_decision.return_value = provisional

        _, outcome = await svc.resolve_single(make_entity_mention())

        assert outcome == ResolutionOutcome.PROVISIONAL
