"""Unit tests for OutcomeIntegrationService — covers UT-001 through UT-005."""
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from erspec.models.ere import EntityMentionResolutionResponse

from ers.ere_result_integrator.domain.errors import (
    OutcomeValidationError,
    TriadNotFoundError,
)
from ers.ere_result_integrator.services.outcome_integration_service import (
    OutcomeIntegrationService,
)
from ers.request_registry.domain.records import ResolutionRequestRecord
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_decision_store.domain.errors import StaleOutcomeError
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_identifier(source="SYS", req="req1", entity="Org") -> EntityMentionIdentifier:
    return EntityMentionIdentifier(source_id=source, request_id=req, entity_type=entity)


def make_cluster(cluster_id="c-001") -> ClusterReference:
    return ClusterReference(cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85)


_UNSET = object()


def make_response(
    timestamp: datetime | None = _UNSET,  # type: ignore[assignment]
    candidates: list[ClusterReference] | None = None,
    ere_request_id: str = "req1:001",
) -> EntityMentionResolutionResponse:
    ts = datetime.now(UTC) if timestamp is _UNSET else timestamp
    return EntityMentionResolutionResponse(
        ere_request_id=ere_request_id,
        entity_mention_id=make_identifier(),
        candidates=candidates if candidates is not None else [make_cluster("c-001"), make_cluster("c-002")],
        timestamp=ts,
    )


def make_decision() -> Decision:
    now = datetime.now(UTC)
    return Decision(
        id="hash",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster(),
        candidates=[],
        created_at=now,
        updated_at=now,
    )


def make_registry_record() -> ResolutionRequestRecord:
    return ResolutionRequestRecord(
        identifiedBy=make_identifier(),
        content="rdf",
        content_type="text/turtle",
        content_hash="a" * 64,
        received_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_registry():
    svc = create_autospec(RequestRegistryService, instance=True)
    svc.get_resolution_request = AsyncMock(return_value=make_registry_record())
    return svc


@pytest.fixture()
def mock_decision_store():
    svc = create_autospec(DecisionStoreService, instance=True)
    svc.store_decision = AsyncMock(return_value=make_decision())
    return svc


@pytest.fixture()
def callback():
    return AsyncMock()


@pytest.fixture()
def service(mock_registry, mock_decision_store, callback):
    return OutcomeIntegrationService(
        registry_service=mock_registry,
        decision_service=mock_decision_store,
        on_outcome_stored=callback,
    )


@pytest.fixture()
def service_no_callback(mock_registry, mock_decision_store):
    return OutcomeIntegrationService(
        registry_service=mock_registry,
        decision_service=mock_decision_store,
    )


# ---------------------------------------------------------------------------
# UT-001: valid response → Decision persisted + callback called
# ---------------------------------------------------------------------------

class TestValidResponse:
    async def test_returns_decision(self, service, mock_decision_store):
        """UT-001: happy path returns Decision from store_decision."""
        result = await service.integrate_outcome(make_response())
        assert isinstance(result, Decision)

    async def test_maps_candidates_correctly(self, service, mock_decision_store):
        """UT-001: candidates[0] → current_placement; candidates[1:] → candidates."""
        c0, c1 = make_cluster("c-000"), make_cluster("c-001")
        await service.integrate_outcome(make_response(candidates=[c0, c1]))
        mock_decision_store.store_decision.assert_called_once()
        call_kwargs = mock_decision_store.store_decision.call_args.kwargs
        assert call_kwargs["current"] == c0
        assert call_kwargs["candidates"] == [c1]

    async def test_single_candidate_produces_empty_alternatives(self, service, mock_decision_store):
        """UT-001 edge case: one candidate → no alternatives."""
        await service.integrate_outcome(make_response(candidates=[make_cluster()]))
        call_kwargs = mock_decision_store.store_decision.call_args.kwargs
        assert call_kwargs["candidates"] == []

    async def test_callback_called_with_correct_triad_key(self, service, callback):
        """UT-001: on_outcome_stored receives direct-concatenation triad_key."""
        await service.integrate_outcome(make_response())
        callback.assert_called_once_with("SYSreq1Org")

    async def test_no_callback_does_not_raise(self, service_no_callback):
        """UT-001 edge case: on_outcome_stored=None does not raise."""
        await service_no_callback.integrate_outcome(make_response())  # must not raise


# ---------------------------------------------------------------------------
# UT-002: StaleOutcomeError → logged at DEBUG + callback still called
# ---------------------------------------------------------------------------

class TestStaleOutcome:
    async def test_stale_does_not_propagate(self, service, mock_decision_store):
        """UT-002: StaleOutcomeError is caught; no exception raised to caller."""
        mock_decision_store.store_decision.side_effect = StaleOutcomeError(
            "SYS", "req1", "Org", stored_at="T1", attempted_at="T0"
        )
        await service.integrate_outcome(make_response())  # must not raise

    async def test_callback_still_called_on_stale(self, service, mock_decision_store, callback):
        """UT-002: on_outcome_stored fires even when outcome is stale."""
        mock_decision_store.store_decision.side_effect = StaleOutcomeError(
            "SYS", "req1", "Org", stored_at="T1", attempted_at="T0"
        )
        await service.integrate_outcome(make_response())
        callback.assert_called_once()

    async def test_stale_logged_at_debug(self, service, mock_decision_store, caplog):
        """UT-002: StaleOutcomeError triggers a DEBUG log."""
        mock_decision_store.store_decision.side_effect = StaleOutcomeError(
            "SYS", "req1", "Org", stored_at="T1", attempted_at="T0"
        )
        with caplog.at_level(logging.DEBUG, logger="ers.ere_result_integrator"):
            await service.integrate_outcome(make_response())
        assert any("stale" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# UT-003: triad not in registry → TriadNotFoundError
# ---------------------------------------------------------------------------

class TestTriadNotFound:
    async def test_raises_triad_not_found(self, service, mock_registry):
        """UT-003: None from registry → TriadNotFoundError."""
        mock_registry.get_resolution_request = AsyncMock(return_value=None)
        with pytest.raises(TriadNotFoundError) as exc_info:
            await service.integrate_outcome(make_response())
        assert exc_info.value.identifier == make_identifier()

    async def test_decision_store_not_called_when_triad_missing(
        self, service, mock_registry, mock_decision_store
    ):
        """UT-003: Decision Store must not be touched when triad is unknown."""
        mock_registry.get_resolution_request = AsyncMock(return_value=None)
        with pytest.raises(TriadNotFoundError):
            await service.integrate_outcome(make_response())
        mock_decision_store.store_decision.assert_not_called()


# ---------------------------------------------------------------------------
# UT-004 / UT-005: validation errors raised before registry query
# ---------------------------------------------------------------------------

class TestValidation:
    async def test_null_timestamp_raises(self, service, mock_registry):
        """UT-004: timestamp=None → OutcomeValidationError before registry."""
        with pytest.raises(OutcomeValidationError) as exc_info:
            await service.integrate_outcome(make_response(timestamp=None))
        assert "timestamp" in exc_info.value.detail.lower()
        mock_registry.get_resolution_request.assert_not_called()

    async def test_empty_candidates_raises(self, service, mock_registry):
        """UT-005: empty candidates → OutcomeValidationError before registry."""
        with pytest.raises(OutcomeValidationError) as exc_info:
            await service.integrate_outcome(make_response(candidates=[]))
        assert "candidates" in exc_info.value.detail.lower()
        mock_registry.get_resolution_request.assert_not_called()


# ---------------------------------------------------------------------------
# Gap B: coordinator callback error — decision persisted, no propagation
# ---------------------------------------------------------------------------


class TestCallbackError:
    async def test_callback_error_does_not_propagate(self, mock_registry, mock_decision_store):
        """Gap B: callback raising does not propagate; service returns the persisted Decision."""
        failing_callback = AsyncMock(side_effect=RuntimeError("coordinator down"))
        svc = OutcomeIntegrationService(
            registry_service=mock_registry,
            decision_service=mock_decision_store,
            on_outcome_stored=failing_callback,
        )
        result = await svc.integrate_outcome(make_response())
        assert isinstance(result, Decision)

    async def test_callback_error_logged_as_error(
        self, mock_registry, mock_decision_store, caplog
    ):
        """Gap B: callback raising triggers an ERROR log mentioning notification failure."""
        failing_callback = AsyncMock(side_effect=RuntimeError("coordinator down"))
        svc = OutcomeIntegrationService(
            registry_service=mock_registry,
            decision_service=mock_decision_store,
            on_outcome_stored=failing_callback,
        )
        with caplog.at_level(logging.ERROR, logger="ers.ere_result_integrator"):
            await svc.integrate_outcome(make_response())

        assert any("notification" in r.message.lower() for r in caplog.records)

    async def test_decision_still_persisted_when_callback_fails(
        self, mock_registry, mock_decision_store
    ):
        """Gap B: store_decision is called even though the callback later fails."""
        failing_callback = AsyncMock(side_effect=RuntimeError("coordinator down"))
        svc = OutcomeIntegrationService(
            registry_service=mock_registry,
            decision_service=mock_decision_store,
            on_outcome_stored=failing_callback,
        )
        await svc.integrate_outcome(make_response())
        mock_decision_store.store_decision.assert_called_once()
