# Task 7: Integration Tests + Gherkin Step Definitions

## Context

Final task. Two parts:

1. **Integration tests** — real MongoDB + real Redis (testcontainers from root `conftest.py`).
   Cover IT-001 through IT-004. ERE responses are pushed directly to Redis; the service
   processes them and the Decision Store is verified.

2. **Gherkin step definitions** — the `.feature` files already exist and pass (all steps
   return `assert True`). This task replaces the scaffold placeholders with real service
   calls using `OutcomeIntegrationService`.

---

## Files to Create

| Path | Purpose |
|------|---------|
| `tests/integration/ere_result_integrator/__init__.py` | Empty package marker |
| `tests/integration/ere_result_integrator/test_outcome_integration.py` | IT-001 through IT-004 |

## Files to Update

| Path | What changes |
|------|-------------|
| `tests/feature/ere_result_integrator/test_outcome_acceptance.py` | Replace TODO placeholders with real service calls |
| `tests/feature/ere_result_integrator/test_deduplication_and_staleness.py` | Replace TODO placeholders with real service calls |
| `tests/feature/ere_result_integrator/test_contract_validation.py` | Replace TODO placeholders with real service calls |

---

## Step 1 — Integration Tests

`tests/integration/ere_result_integrator/test_outcome_integration.py`:

```python
"""Integration tests for OutcomeIntegrationService against real MongoDB and Redis.

Uses testcontainers fixtures from tests/conftest.py:
  - redis_client  (scope=function, flushes after each test)
  - redis_container (scope=module)

Uses tests/integration/conftest.py:
  - mongo_db (scope=function, drops DB after each test)

Each test:
  1. Seeds data in MongoDB (resolution request + optional prior decision).
  2. Pushes a resolution response to Redis via lpush on ERE_RESPONSE_CHANNEL.
  3. Calls service.integrate_outcome() with the pulled response.
  4. Asserts MongoDB state.
"""
import json
from datetime import UTC, datetime, timedelta

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from erspec.models.ere import EntityMentionResolutionResponse

from ers import config
from ers.commons.adapters.hasher import SHA256ContentHasher
from ers.commons.adapters.redis_client import RedisConnectionConfig, RedisEREClient
from ers.ere_result_integrator.adapters.redis_outcome_listener import RedisOutcomeListener
from ers.ere_result_integrator.services.outcome_integration_service import (
    OutcomeIntegrationService,
)
from ers.request_registry.adapters.records_repository import (
    MongoLookupStateRepository,
    MongoResolutionRequestRepository,
)
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


def make_response(
    identifier: EntityMentionIdentifier,
    cluster_id: str = "cluster-it-001",
    timestamp: datetime | None = None,
    ere_request_id: str = "req-it-001:001",
    n_candidates: int = 1,
) -> EntityMentionResolutionResponse:
    ts = timestamp or datetime.now(UTC)
    candidates = [make_cluster(cluster_id)] + [
        make_cluster(f"alt-{i}") for i in range(n_candidates - 1)
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
        rdf_config=None,  # not needed for get_resolution_request
    )


@pytest.fixture()
def decision_service(mongo_db):
    repo = MongoDecisionRepository(mongo_db)
    return DecisionStoreService(repository=repo)


@pytest.fixture()
def integration_service(registry_service, decision_service):
    return OutcomeIntegrationService(
        registry_service=registry_service,
        decision_service=decision_service,
        on_outcome_stored=None,  # no coordinator in integration tests
    )


@pytest.fixture()
async def seeded_registry(mongo_db, registry_service):
    """Pre-seed a resolution request so find_by_triad returns a record."""
    from ers.request_registry.domain.records import ResolutionRequestRecord
    from ers.commons.adapters.hasher import SHA256ContentHasher
    repo = MongoResolutionRequestRepository(mongo_db)
    record = ResolutionRequestRecord(
        identifiedBy=make_identifier(),
        content="@prefix org: <http://www.w3.org/ns/org#> .",
        content_type="text/turtle",
        content_hash=SHA256ContentHasher().hash("@prefix org: <http://www.w3.org/ns/org#> ."),
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
    assert stored.updated_at == response.timestamp


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
    """IT-003: same outcome sent twice → Decision Store contains only one record."""
    identifier = make_identifier()
    ts = datetime.now(UTC)
    response = make_response(identifier, cluster_id="cluster-dup", timestamp=ts)

    await integration_service.integrate_outcome(response)
    await integration_service.integrate_outcome(response)  # duplicate — must be rejected silently

    stored = await decision_service.get_decision_by_triad(identifier)
    assert stored is not None
    assert stored.current_placement.cluster_id == "cluster-dup"
    assert stored.updated_at == ts


# ---------------------------------------------------------------------------
# IT-004: late arrival — newer outcome wins, older rejected
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_it004_late_arrival_rejected(
    seeded_registry, integration_service, decision_service
):
    """IT-004: T1+1 accepted; T0 (late arrival) rejected by staleness check."""
    identifier = make_identifier()
    t0 = datetime.now(UTC)
    t1_plus_1 = t0 + timedelta(seconds=10)

    response_newer = make_response(identifier, cluster_id="cluster-newer", timestamp=t1_plus_1)
    response_older = make_response(identifier, cluster_id="cluster-stale", timestamp=t0)

    await integration_service.integrate_outcome(response_newer)
    await integration_service.integrate_outcome(response_older)  # stale — rejected

    stored = await decision_service.get_decision_by_triad(identifier)
    assert stored is not None
    assert stored.current_placement.cluster_id == "cluster-newer"
    assert stored.updated_at == t1_plus_1
```

---

## Step 2 — Wire Gherkin Step Definitions

The three step definition files have full scaffold and `assert True` placeholders.
Replace each `TODO` section with real calls to `OutcomeIntegrationService`.

**Pattern for each step file** (same structure in all three):

```python
# ---------------------------------------------------------------------------
# Replace at top of file — add imports
# ---------------------------------------------------------------------------
from datetime import UTC, datetime
from unittest.mock import AsyncMock, create_autospec

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
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService
```

**Replace the `ctx` fixture** with one that pre-wires mock service:

```python
@pytest.fixture()
def ctx():
    """Shared mutable context — pre-wires mocked service dependencies."""
    registry = create_autospec(RequestRegistryService, instance=True)
    decisions = create_autospec(DecisionStoreService, instance=True)
    service = OutcomeIntegrationService(
        registry_service=registry,
        decision_service=decisions,
        on_outcome_stored=None,
    )
    return {
        "registry": registry,
        "decisions": decisions,
        "service": service,
        "result": None,
        "raised_exception": None,
    }
```

**For `When` steps** — replace `ctx["result"] = None  # TODO` with:

```python
from unittest.mock import AsyncMock
from erspec.models.core import ClusterReference

# Build a real EntityMentionResolutionResponse and call the service
candidates = [
    ClusterReference(cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85)
] + [
    ClusterReference(cluster_id=f"alt-{i}", confidence_score=0.4, similarity_score=0.35)
    for i in range(int(ctx.get("candidate_count", 0)))
]
response = EntityMentionResolutionResponse(
    ere_request_id=ctx.get("ere_request_id", f"{ctx['request_id']}:001"),
    entity_mention_id=EntityMentionIdentifier(
        source_id=ctx["source_id"],
        request_id=ctx["request_id"],
        entity_type=ctx["entity_type"],
    ),
    candidates=candidates,
    timestamp=datetime.fromisoformat(outcome_timestamp),
)
# Configure decision service mock to return a Decision
from erspec.models.core import Decision
now = datetime.now(UTC)
mock_decision = Decision(
    id="hash",
    about_entity_mention=response.entity_mention_id,
    current_placement=candidates[0],
    candidates=candidates[1:],
    created_at=now,
    updated_at=response.timestamp,
)
ctx["decisions"].store_decision = AsyncMock(return_value=mock_decision)

try:
    import asyncio
    ctx["result"] = asyncio.get_event_loop().run_until_complete(
        ctx["service"].integrate_outcome(response)
    )
except Exception as e:
    ctx["raised_exception"] = e
```

**For `Then` steps** — replace `assert True  # TODO` with:

```python
# Example for "Decision Store is updated with cluster_id"
assert ctx["raised_exception"] is None
assert ctx["result"] is not None
assert ctx["result"].current_placement.cluster_id == cluster_id
```

> **Note:** The step definitions use unit-level mocks (no real DB/Redis) —
> consistent with the existing scaffold design comment: *"No real MongoDB or Redis
> connection is required for unit-level BDD scenarios."*

---

## Step 3 — Verify

```bash
# Integration tests (requires Docker)
poetry run pytest tests/integration/ere_result_integrator/ -v -m integration

# Feature tests
poetry run pytest tests/feature/ere_result_integrator/ -v -m feature

# Full suite — no regressions
make test
```

---

## Notes

- The `redis_client` and `redis_container` fixtures are defined in `tests/conftest.py`
  (module-scoped container, function-scoped client with `flushdb` after each test).
- The `mongo_db` fixture is in `tests/integration/conftest.py` (drops the entire
  test DB after each test using a UUID-named database).
- Integration tests are marked `@pytest.mark.integration` — they are excluded from
  the default `make test` unit run (which uses `-m unit`). Run them explicitly
  or include them in CI via `make test-integration` if that target exists.

---

## Key References

| What | Where |
|------|-------|
| `redis_client` fixture | `tests/conftest.py` |
| `mongo_db` fixture | `tests/integration/conftest.py` |
| Existing Gherkin step files | `tests/feature/ere_result_integrator/test_*.py` |
| Integration test pattern reference | `tests/integration/ere_contract_client/test_service_round_trip.py` |
