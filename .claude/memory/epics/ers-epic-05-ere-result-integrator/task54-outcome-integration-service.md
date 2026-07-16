# Task 4: Outcome Integration Service

## Context

The core service layer. Orchestrates the 6-step integration algorithm: validate →
registry check → map → persist → notify. Uses `RequestRegistryService` (EPIC-01) for
registry checks and `DecisionStoreService` (EPIC-04) for persistence. The optional
`on_outcome_stored` callback wires to `AsyncResolutionWaiter.notify` (EPIC-06) at
runtime — injected by EPIC-07 lifespan, never imported directly.

---

## Files to Create

| Path | Purpose |
|------|---------|
| `src/ers/ere_result_integrator/services/__init__.py` | Empty package marker |
| `src/ers/ere_result_integrator/services/outcome_integration_service.py` | `OutcomeIntegrationService` |

---

## Step 1 — Write Failing Tests First (TDD)

Create `tests/unit/ere_result_integrator/services/__init__.py` (empty) and
`tests/unit/ere_result_integrator/services/test_outcome_integration_service.py`:

```python
"""Unit tests for OutcomeIntegrationService — covers UT-001 through UT-005."""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, create_autospec, patch

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


def make_response(
    timestamp: datetime | None = None,
    candidates: list[ClusterReference] | None = None,
    ere_request_id: str = "req1:001",
) -> EntityMentionResolutionResponse:
    return EntityMentionResolutionResponse(
        ere_request_id=ere_request_id,
        entity_mention_id=make_identifier(),
        candidates=candidates if candidates is not None else [make_cluster("c-001"), make_cluster("c-002")],
        timestamp=timestamp if timestamp is not None else datetime.now(UTC),
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_registry():
    svc = create_autospec(RequestRegistryService, instance=True)
    svc.get_resolution_request = AsyncMock(return_value=ResolutionRequestRecord(
        identifiedBy=make_identifier(),
        content="rdf",
        content_type="text/turtle",
        content_hash="a" * 64,
        received_at=datetime.now(UTC),
    ))
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
        response = make_response()
        result = await service.integrate_outcome(response)
        assert isinstance(result, Decision)

    async def test_maps_candidates_correctly(self, service, mock_decision_store):
        """UT-001: candidates[0] → current_placement; candidates[1:] → candidates."""
        c0, c1 = make_cluster("c-000"), make_cluster("c-001")
        response = make_response(candidates=[c0, c1])
        await service.integrate_outcome(response)
        mock_decision_store.store_decision.assert_called_once()
        _, kwargs = mock_decision_store.store_decision.call_args
        assert kwargs["current"] == c0
        assert kwargs["candidates"] == [c1]

    async def test_single_candidate_produces_empty_alternatives(self, service, mock_decision_store):
        """UT-001 edge case: one candidate → no alternatives."""
        response = make_response(candidates=[make_cluster()])
        await service.integrate_outcome(response)
        _, kwargs = mock_decision_store.store_decision.call_args
        assert kwargs["candidates"] == []

    async def test_callback_called_with_correct_triad_key(self, service, callback):
        """UT-001: on_outcome_stored receives direct-concatenation triad_key."""
        response = make_response()
        await service.integrate_outcome(response)
        expected_key = "SYSreq1Org"
        callback.assert_called_once_with(expected_key)

    async def test_no_callback_does_not_raise(self, service_no_callback):
        """UT-001 edge case: on_outcome_stored=None does not raise."""
        response = make_response()
        await service_no_callback.integrate_outcome(response)  # must not raise


# ---------------------------------------------------------------------------
# UT-002: StaleOutcomeError → logged at DEBUG + callback still called
# ---------------------------------------------------------------------------

class TestStaleOutcome:
    async def test_stale_does_not_propagate(self, service, mock_decision_store):
        """UT-002: StaleOutcomeError is caught; no exception raised to caller."""
        mock_decision_store.store_decision.side_effect = StaleOutcomeError(
            "SYS", "req1", "Org", stored_at="T1", attempted_at="T0"
        )
        response = make_response()
        await service.integrate_outcome(response)  # must not raise

    async def test_callback_still_called_on_stale(self, service, mock_decision_store, callback):
        """UT-002: on_outcome_stored fires even when outcome is stale."""
        mock_decision_store.store_decision.side_effect = StaleOutcomeError(
            "SYS", "req1", "Org", stored_at="T1", attempted_at="T0"
        )
        response = make_response()
        await service.integrate_outcome(response)
        callback.assert_called_once()

    async def test_stale_logged_at_debug(self, service, mock_decision_store, caplog):
        """UT-002: StaleOutcomeError triggers a DEBUG log."""
        import logging
        mock_decision_store.store_decision.side_effect = StaleOutcomeError(
            "SYS", "req1", "Org", stored_at="T1", attempted_at="T0"
        )
        response = make_response()
        with caplog.at_level(logging.DEBUG, logger="ers.ere_result_integrator"):
            await service.integrate_outcome(response)
        assert any("stale" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# UT-003: triad not in registry → TriadNotFoundError
# ---------------------------------------------------------------------------

class TestTriadNotFound:
    async def test_raises_triad_not_found(self, service, mock_registry):
        """UT-003: None from registry → TriadNotFoundError."""
        mock_registry.get_resolution_request = AsyncMock(return_value=None)
        response = make_response()
        with pytest.raises(TriadNotFoundError) as exc_info:
            await service.integrate_outcome(response)
        assert exc_info.value.identifier == response.entity_mention_id

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
        response = make_response(timestamp=None)
        with pytest.raises(OutcomeValidationError) as exc_info:
            await service.integrate_outcome(response)
        assert "timestamp" in exc_info.value.detail.lower()
        mock_registry.get_resolution_request.assert_not_called()

    async def test_empty_candidates_raises(self, service, mock_registry):
        """UT-005: empty candidates → OutcomeValidationError before registry."""
        response = make_response(candidates=[])
        with pytest.raises(OutcomeValidationError) as exc_info:
            await service.integrate_outcome(response)
        assert "candidates" in exc_info.value.detail.lower()
        mock_registry.get_resolution_request.assert_not_called()
```

---

## Step 2 — Implement the Service

`src/ers/ere_result_integrator/services/outcome_integration_service.py`:

```python
"""Outcome Integration Service — orchestrates ERE result absorption (EPIC-05).

Algorithm (6 steps from EPIC-05 §2.3):
  1. Validate message contract (timestamp, candidates).
  2. Extract identifier from response.
  3. Query Request Registry — reject unknown triads.
  4. Map response fields to store_decision() arguments.
  5. Persist to Decision Store — catch StaleOutcomeError.
  6. Notify coordinator via injected callback.
"""
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from erspec.models.core import Decision, EntityMentionIdentifier
from erspec.models.ere import EntityMentionResolutionResponse

from ers.ere_result_integrator.domain.errors import (
    OutcomeValidationError,
    TriadNotFoundError,
)
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_decision_store.domain.errors import StaleOutcomeError
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

_log = logging.getLogger(__name__)


class OutcomeIntegrationService:
    """Orchestrates ERE outcome validation, persistence, and coordinator notification.

    Args:
        registry_service: Used to verify the triad exists in the Request Registry.
        decision_service: Used to atomically persist the cluster assignment.
        on_outcome_stored: Optional async callback called after every persist attempt
            (including stale rejections). At runtime this is ``AsyncResolutionWaiter.notify``
            injected by the EPIC-07 lifespan. ``None`` is valid (testing / isolation mode).
    """

    def __init__(
        self,
        registry_service: RequestRegistryService,
        decision_service: DecisionStoreService,
        on_outcome_stored: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._registry = registry_service
        self._decisions = decision_service
        self._on_outcome_stored = on_outcome_stored

    async def integrate_outcome(
        self, response: EntityMentionResolutionResponse
    ) -> Decision | None:
        """Process one ERE resolution response end-to-end.

        Args:
            response: Deserialized ERE response from ``AsyncOutcomeListener.consume()``.

        Returns:
            The persisted ``Decision``, or ``None`` on stale rejection.

        Raises:
            OutcomeValidationError: If ``timestamp`` is ``None`` or ``candidates`` is empty.
            TriadNotFoundError: If the triad is not registered in the Request Registry.
        """
        # Step 1 — validate message contract
        if response.timestamp is None:
            raise OutcomeValidationError("timestamp is None; ERE response must carry a timestamp")
        if not response.candidates:
            raise OutcomeValidationError("candidates is empty; ERE response must have at least one candidate")

        # Step 2 — extract identifier
        identifier: EntityMentionIdentifier = response.entity_mention_id

        # Step 3 — registry check
        record = await self._registry.get_resolution_request(identifier)
        if record is None:
            raise TriadNotFoundError(identifier)

        # Step 4 — map response to store_decision() arguments
        current = response.candidates[0]
        candidates = response.candidates[1:]
        updated_at: datetime = response.timestamp

        # Step 5 — persist (catch stale; always proceed to notify)
        decision: Decision | None = None
        try:
            decision = await self._decisions.store_decision(
                identifier=identifier,
                current=current,
                candidates=candidates,
                updated_at=updated_at,
            )
        except StaleOutcomeError:
            _log.debug(
                "Stale outcome rejected",
                extra={
                    "source_id": identifier.source_id,
                    "request_id": identifier.request_id,
                    "entity_type": identifier.entity_type,
                    "ere_request_id": response.ere_request_id,
                },
            )

        # Step 6 — notify coordinator (doorbell, not data pipe)
        if self._on_outcome_stored is not None:
            triad_key = f"{identifier.source_id}{identifier.request_id}{identifier.entity_type}"
            await self._on_outcome_stored(triad_key)

        return decision
```

---

## Step 3 — Verify

```bash
poetry run pytest tests/unit/ere_result_integrator/services/ -v
```

All 12 tests must pass.

---

## Key References

| What | Where |
|------|-------|
| `RequestRegistryService.get_resolution_request()` | `src/ers/request_registry/services/request_registry_service.py` |
| `DecisionStoreService.store_decision()` | `src/ers/resolution_decision_store/services/decision_store_service.py` |
| `StaleOutcomeError` | `src/ers/resolution_decision_store/domain/errors.py` |
| Domain errors (Task 1) | `src/ers/ere_result_integrator/domain/errors.py` |
| `triad_key` format | Direct concatenation `f"{source_id}{request_id}{entity_type}"` — no separator; matches EPIC-06 §5.3 |
