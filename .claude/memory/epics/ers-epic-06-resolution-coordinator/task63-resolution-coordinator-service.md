# Task 6.3 — ResolutionCoordinatorService (Spines A + B)

## Goal

Implement `ResolutionCoordinatorService` — the orchestrator for single-mention and bulk
resolution. This replaces the temporary `ResolutionCoordinatorServiceABC` stub entirely.

---

## Timeout Model (Simplified)

Two config values, two roles:

| Config | Default | Used in | What it does |
|--------|---------|---------|--------------|
| `ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET` | 30s | `resolve_single` | Waits this long for ERE; on timeout → issues provisional and returns. NOT a fatal exception. |
| `ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET` | 120s | `resolve_bulk` outer wrap | Hard stop for the whole batch. On timeout → `ResolutionTimeoutException`. |

`SINGLE_REQUEST_TIME_BUDGET` doubles as the ERE wait window. If ERE responds before the
budget expires → canonical decision. If budget expires before ERE responds → provisional
issued and returned to the client. No separate ERE window config needed.

`ResolutionTimeoutException` is raised only when:
1. The bulk budget expires before all mentions complete, OR
2. The Decision Store is unavailable while trying to write a provisional (cannot produce any response).

---

## Scope

### What to build

**Replace** `src/ers/resolution_coordinator/services/resolution_coordinator_service.py`
(current file contains only the temp ABC — delete it entirely and write from scratch).

#### Class: `ResolutionCoordinatorService`

Constructor dependencies (all injected):

```python
def __init__(
    self,
    registry_service: RequestRegistryService,
    ere_publish_service: EREPublishService,
    decision_store_service: DecisionStoreService,
    waiter: AsyncResolutionWaiter,
) -> None:
```

Config is read directly from `from ers import config` — NOT passed as a constructor
argument. Runtime guard on startup:

```python
if config.ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET <= 0:
    raise ValueError("ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET must be > 0")
if config.ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET <= 0:
    raise ValueError("ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET must be > 0")
```

#### Method: `resolve_single(entity_mention: EntityMention) -> Decision`

Simplified algorithm (compared to original spec — see Design Changes below):

```
1. REGISTER
   try:
       await registry_service.register_resolution_request(entity_mention)
   except (ValueError, MalformedRDFError, ContentTooLargeError,
           UnsupportedEntityTypeError, EntityTypeMismatchError,
           MultipleEntitiesFoundError, EmptyExtractionError) as e:
       raise ParsingFailedException(str(e), cause=e)
   # IdempotencyConflictError propagates directly (do not catch or wrap)

2. CHECK EXISTING DECISION
   identifier = entity_mention.identifiedBy
   existing = await decision_store_service.get_decision_by_triad(identifier)
   if existing is not None:
       return existing
   # No waiter created, no publish — instant return for replays with decisions.

3+4+5. WAITER LIFECYCLE: PUBLISH → WAIT → PROVISIONAL FALLBACK
   triad_key = f"{identifier.source_id}{identifier.request_id}{identifier.entity_type}"
   event = await waiter.get_or_create(triad_key)
   try:
       try:
           request = EntityMentionResolutionRequest(
               entity_mention=entity_mention, ere_request_id="",
           )  # ere_request_id auto-populated by EREPublishService._enrich_metadata
           await ere_publish_service.publish_request(request)
           await asyncio.wait_for(
               asyncio.shield(event.wait()),
               timeout=config.ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET,
           )
           decision = await decision_store_service.get_decision_by_triad(identifier)
           if decision is not None:
               return decision
           # decision vanished between ERE write and our read — fall through to provisional
       except (RedisConnectionError, ChannelUnavailableError, asyncio.TimeoutError):
           pass   # all three → provisional fallback

       return await self._issue_provisional(identifier)
   finally:
       try:
           await asyncio.shield(waiter.release(triad_key))
       except (asyncio.CancelledError, Exception):
           pass
```

#### Private method: `_issue_provisional(identifier: EntityMentionIdentifier) -> Decision`

Extracted for readability and SRP:

```python
async def _issue_provisional(self, identifier: EntityMentionIdentifier) -> Decision:
    provisional_id = derive_provisional_cluster_id(identifier)
    cluster_ref = ClusterReference(
        cluster_id=provisional_id, confidence_score=1.0, similarity_score=1.0,
    )
    try:
        return await self._decision_store_service.store_decision(
            identifier=identifier,
            current=cluster_ref,
            candidates=[cluster_ref],
            updated_at=datetime.now(UTC),
        )
    except StaleOutcomeError:
        return await self._decision_store_service.get_decision_by_triad(identifier)
    except RepositoryConnectionError as e:
        raise ResolutionTimeoutException(
            f"Cannot persist provisional decision: {e}"
        ) from None
```

#### Method: `resolve_bulk(entity_mentions: list[EntityMention]) -> list[Decision | CoordinatorException]`

```python
async def resolve_bulk(self, entity_mentions: list[EntityMention]) -> list[Decision | CoordinatorException]:
    if not entity_mentions:
        return []
    tasks = [self.resolve_single(mention) for mention in entity_mentions]
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=config.ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET,
        )
        return list(results)
    except asyncio.TimeoutError:
        raise ResolutionTimeoutException(
            "Bulk resolution exceeded client time budget"
        )
```

#### Public module-level API (OTel tracing)

Per project conventions (`CLAUDE.md`), `@trace_function` goes on module-level public
functions, not class methods:

```python
@trace_function(span_name="resolution_coordinator.resolve_single")
async def resolve_single(
    entity_mention: EntityMention,
    service: ResolutionCoordinatorService,
) -> Decision:
    return await service.resolve_single(entity_mention)


@trace_function(span_name="resolution_coordinator.resolve_bulk")
async def resolve_bulk(
    entity_mentions: list[EntityMention],
    service: ResolutionCoordinatorService,
) -> list[Decision | CoordinatorException]:
    return await service.resolve_bulk(entity_mentions)
```

### What NOT to build
- No REST API wiring (Task 6.7)
- No new domain models — import `EntityMention`, `ClusterReference`, `Decision`,
  `EntityMentionResolutionRequest` from erspec; `EntityMentionIdentifier` from erspec
- No new adapter code — call services only
- No logging inside `AsyncResolutionWaiter` or utility functions (per EPIC §10.6)
- No retry logic for ERE publish — on failure, issue provisional (EPIC §7 anti-pattern)

---

## Design Changes from Original Spec

### 1. `EnginePublishFailedException` removed as internal control flow

**Original**: Step 3 raised `EnginePublishFailedException` internally, caught in an outer
`try/except` to reach the provisional path. Three levels of nesting.

**Changed**: Catch `RedisConnectionError` and `ChannelUnavailableError` directly alongside
`asyncio.TimeoutError` — all three lead to the same provisional fallback. One `except`
clause, one level of nesting.

**Why**: Using exceptions as goto creates structural complexity for no benefit. The
exception never reached the caller — it was purely internal control flow.
`EnginePublishFailedException` stays in the hierarchy (T6.1) for potential future use
by EPIC-07 exception handlers, but is not raised in `resolve_single`.

### 2. `ChannelUnavailableError` caught alongside `RedisConnectionError`

**Original**: Only `RedisConnectionError` triggered the provisional path.

**Changed**: `ChannelUnavailableError` (Redis up but ERE not subscribed, or channel
timeout) is functionally equivalent — ERE won't process the request. Both trigger
provisional.

### 3. `get_or_create` moved before publish

**Original**: `get_or_create` was in step 4 (after publish). If publish failed, waiter
was never touched.

**Changed**: `get_or_create` before publish. With `WeakValueDictionary` (T6.2), creating
then immediately releasing an event has zero cost. This collapses the entire post-register
flow into a single `try/finally` block for the waiter lifecycle.

### 4. `_issue_provisional` extracted as private method

**Original**: Provisional logic inline in `resolve_single` (10+ lines).

**Changed**: Extracted to `_issue_provisional(identifier)`. Keeps `resolve_single`
readable and the `RepositoryConnectionError → ResolutionTimeoutException` mapping
testable.

### 5. `ValueError` added to parsing catch list

**Original**: Catch list missed `ValueError`.

**Changed**: `RequestRegistryService.register_resolution_request` raises `ValueError`
for empty content. This is a parsing-adjacent failure that should be wrapped in
`ParsingFailedException`.

---

## asyncio Cancellation Safety in `finally`

When `resolve_bulk`'s budget expires, Python sends `CancelledError` to each running
`resolve_single` coroutine. The `finally` block must still release the waiter.
Using `asyncio.shield(waiter.release(triad_key))` schedules the release as a separate
task that survives the cancellation of the parent coroutine:

```python
finally:
    try:
        await asyncio.shield(waiter.release(triad_key))
    except (asyncio.CancelledError, Exception):
        pass
```

The `except` swallows the `CancelledError` that `await asyncio.shield(...)` re-raises
(the shield schedules the inner coroutine but immediately re-raises the cancellation on
the outer `await`). The release still completes in the background.

---

## Imports to Use

```python
import asyncio
from datetime import UTC, datetime

from erspec.models.core import ClusterReference, Decision, EntityMention, EntityMentionIdentifier
from erspec.models.ere import EntityMentionResolutionRequest

from ers import config
from ers.commons.adapters.tracing import trace_function
from ers.ere_contract_client.domain.errors import ChannelUnavailableError, RedisConnectionError
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from ers.rdf_mention_parser.domain.exceptions import (
    ContentTooLargeError, EmptyExtractionError, EntityTypeMismatchError,
    MalformedRDFError, MultipleEntitiesFoundError, UnsupportedEntityTypeError,
)
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_coordinator.domain.exceptions import (
    CoordinatorException, ParsingFailedException, ResolutionTimeoutException,
)
from ers.resolution_coordinator.services.async_resolution_waiter import AsyncResolutionWaiter
from ers.resolution_decision_store.adapters.provisional_id import derive_provisional_cluster_id
from ers.resolution_decision_store.domain.errors import (
    RepositoryConnectionError, StaleOutcomeError,
)
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService
```

---

## Files to Create / Modify

| Action | File |
|--------|------|
| Replace | `src/ers/resolution_coordinator/services/resolution_coordinator_service.py` |
| Create  | `tests/unit/resolution_coordinator/services/test_resolution_coordinator_service.py` |

---

## Unit Tests

All tests are `async`. Use `AsyncMock` (from `unittest.mock`) for all async service methods.
Use a real `AsyncResolutionWaiter` instance where the waiter's actual async behaviour
matters (e.g., wait/notify interaction); use `AsyncMock` where the waiter call is
just a side-effect stub.

### Fixture pattern

```python
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
    return ResolutionCoordinatorService(registry_svc, publish_svc, decision_svc, waiter)
```

### Test cases (all scenarios)

| ID | Scenario | Key setup | Expected |
|----|----------|-----------|----------|
| TC-001 | `__init__` rejects zero/negative budget | Monkeypatch `SINGLE_REQUEST_TIME_BUDGET=0` | `ValueError` on construction |
| TC-002 | Happy path — ERE responds in time | Real `AsyncResolutionWaiter`; `notify` fired before budget | `Decision` with ERE cluster ID |
| TC-003 | ERE budget timeout → provisional | Event never fires; `SINGLE_REQUEST_TIME_BUDGET` monkeypatched to 0.05s | Provisional `Decision`; `store_decision` called |
| TC-004 | Redis down → provisional | `publish_svc.publish_request` raises `RedisConnectionError` | Provisional `Decision`; no event wait |
| TC-004b | Channel unavailable → provisional | `publish_svc.publish_request` raises `ChannelUnavailableError` | Provisional `Decision`; no event wait |
| TC-005 | Idempotent — decision exists | `decision_svc.get_decision_by_triad` returns existing Decision | Existing `Decision`; `publish_request` NOT called; `waiter.get_or_create` NOT called |
| TC-006 | Idempotent — no decision yet | `get_decision_by_triad` returns None; ERE responds in time | Canonical Decision; `publish_request` called once |
| TC-007 | Idempotency conflict | `registry_svc.register_resolution_request` raises `IdempotencyConflictError` | `IdempotencyConflictError` propagated; `store_decision` NOT called |
| TC-008 | Parse failure — MalformedRDF | `register_resolution_request` raises `MalformedRDFError` | `ParsingFailedException` raised; `publish_request` NOT called |
| TC-009 | Parse failure — ValueError (empty content) | `register_resolution_request` raises `ValueError` | `ParsingFailedException` raised |
| TC-010 | Decision Store unavailable on provisional write | `store_decision` raises `RepositoryConnectionError` | `ResolutionTimeoutException` raised |
| TC-011 | Stale provisional write | `store_decision` raises `StaleOutcomeError`; `get_decision_by_triad` returns ERE decision | ERE `Decision` returned; no exception |
| TC-012 | Bulk — all succeed | 3 mentions; all ERE respond in time | List of 3 canonical Decisions in input order |
| TC-013 | Bulk — partial parse failure | 3 mentions; mention 2 malformed | List: [Decision, ParsingFailedException, Decision] |
| TC-014 | Bulk — empty input | `resolve_bulk([])` | Returns `[]` |
| TC-015 | Bulk — bulk budget exceeded | `BULK_REQUEST_TIME_BUDGET` monkeypatched to 0.01s; all mentions hang | `ResolutionTimeoutException` raised |
| TC-016 | `waiter.release` called on success | Happy path | `waiter.release` called exactly once |
| TC-017 | `waiter.release` called on ERE timeout | Budget expires path | `waiter.release` called exactly once |
| TC-018 | `waiter.release` called on Redis failure | Redis down path | `waiter.release` called exactly once |
| TC-019 | No waiter call on instant decision return | `get_decision_by_triad` returns decision immediately | `waiter.get_or_create` NOT called |

For TC-002 (real event firing), use a real `AsyncResolutionWaiter` and schedule `notify`
with `asyncio.create_task`:

```python
async def test_happy_path_ere_responds(registry_svc, publish_svc, decision_svc):
    real_waiter = AsyncResolutionWaiter()
    svc = ResolutionCoordinatorService(registry_svc, publish_svc, decision_svc, real_waiter)
    triad_key = "SYSTEM_Areq-001Organization"

    # Decision Store returns None first (no existing), then the ERE decision
    ere_decision = make_decision(cluster_id="cl-canonical")
    decision_svc.get_decision_by_triad.side_effect = [None, ere_decision]

    async def signal_ere():
        await asyncio.sleep(0.05)
        await real_waiter.notify(triad_key)

    asyncio.create_task(signal_ere())
    result = await svc.resolve_single(make_entity_mention("SYSTEM_A", "req-001"))
    assert result.current_placement.cluster_id == "cl-canonical"
```

---

## Definition of Done

- [ ] Temp ABC removed; `resolution_coordinator_service.py` contains only `ResolutionCoordinatorService` and two public functions
- [ ] All unit tests pass: `poetry run pytest tests/unit/resolution_coordinator/services/test_resolution_coordinator_service.py -v`
- [ ] `waiter.release` always called in `finally` (verified by TC-016, TC-017, TC-018)
- [ ] `poetry run pylint src/ers/resolution_coordinator/services/resolution_coordinator_service.py` — no errors
- [ ] `poetry run pytest tests/unit/resolution_coordinator/ -v --cov=src/ers/resolution_coordinator --cov-report=term-missing` — coverage ≥ 90%
