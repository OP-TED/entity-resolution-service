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

Full algorithm — refer to EPIC §5.1 for the Mermaid flowchart. Precise implementation:

```
_inner() coroutine:

1. PARSE + REGISTER
   try:
       record = await registry_service.register_resolution_request(entity_mention)
   except (MalformedRDFError, ContentTooLargeError, UnsupportedEntityTypeError,
           EntityTypeMismatchError, MultipleEntitiesFoundError, EmptyExtractionError) as e:
       raise ParsingFailedException(str(e), cause=e)
   # IdempotencyConflictError propagates directly (do not catch or wrap)

2. IDEMPOTENT REPLAY CHECK
   identifier = entity_mention.identifiedBy
   triad_key  = f"{identifier.source_id}{identifier.request_id}{identifier.entity_type}"

   if record is an idempotent replay (detect via: the record was already in the registry,
   i.e. record.received_at predates this call — simplest: check if a decision already
   exists in the store):
       existing = await decision_store_service.get_decision_by_triad(identifier)
       if existing is not None:
           return existing
       # No decision yet → fall through to step 4 (share existing event, skip publish)
       skip_publish = True
   else:
       skip_publish = False

   NOTE on detecting replay vs new:
   `register_resolution_request` does not return a flag distinguishing new vs replay.
   Use the registry record's `received_at` vs `datetime.now(UTC)` is fragile.
   Better approach: attempt the Decision Store lookup unconditionally for replay path.
   See "Idempotency Detection" design note below.

3. PUBLISH TO ERE (skip if skip_publish)
   if not skip_publish:
       try:
           request = EntityMentionResolutionRequest(entity_mention=entity_mention)
           await ere_publish_service.publish_request(request)
       except RedisConnectionError as e:
           raise EnginePublishFailedException(str(e), cause=e)

4. WAIT FOR ERE RESPONSE
   event = await waiter.get_or_create(triad_key)
   try:
       try:
           await asyncio.wait_for(
               asyncio.shield(event.wait()),
               timeout=config.ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET,
           )
           # Event fired — read authoritative decision
           decision = await decision_store_service.get_decision_by_triad(identifier)
           return decision
       except asyncio.TimeoutError:
           pass   # fall through to provisional

5. ISSUE PROVISIONAL (reached from: EnginePublishFailedException OR ERE timeout)
   provisional_id = derive_provisional_cluster_id(identifier)
   cluster_ref    = ClusterReference(cluster_id=provisional_id,
                                     confidence_score=1.0, similarity_score=1.0)
   try:
       decision = await decision_store_service.store_decision(
           identifier=identifier,
           current=cluster_ref,
           candidates=[cluster_ref],
           updated_at=datetime.now(UTC),
       )
   except StaleOutcomeError:
       # ERE already wrote a newer decision before we could write provisional
       decision = await decision_store_service.get_decision_by_triad(identifier)
   return decision

   finally (always, even on exception or cancellation):
       try:
           await asyncio.shield(waiter.release(triad_key))
       except (asyncio.CancelledError, Exception):
           pass   # release scheduled via shield; don't suppress outer cancellation

   NOTE: There is no separate outer wrap for `resolve_single`. The
   `SINGLE_REQUEST_TIME_BUDGET` is consumed entirely by the ERE wait in step 4.
   If step 4 times out → provisional is issued and returned (not a fatal exception).
   `ResolutionTimeoutException` is raised only if the provisional write itself fails
   (e.g. MongoDB unavailable in step 5).
```

#### Idempotency Detection Design Note

`RequestRegistryService.register_resolution_request` returns the existing
`ResolutionRequestRecord` on idempotent replay (same triad + same hash) without
raising. The coordinator cannot distinguish "new record" from "existing record"
from the return value alone since both return a `ResolutionRequestRecord`.

**Decision:** The coordinator always attempts `get_decision_by_triad` after registration.
- If a decision exists → return it (works for both new and replay cases where ERE was fast)
- If no decision → proceed to publish + wait
- For true replays where ERE has not responded yet, `get_or_create` will find the
  existing Event (created by the first request's `resolve_single`) and increment its
  count — the publish is skipped only if we can confirm the record already existed.

**Simplest correct approach**: always call `get_decision_by_triad` first; if found, return
immediately; if not, always publish (ERE is idempotent on the triad key — duplicate
publishes are safe per EPIC §10 constraint 4).

This avoids the "detect replay vs new" complexity entirely:

```
1. register_resolution_request(mention)   → record (or raise)
2. existing = get_decision_by_triad(id)
   if existing: return existing
3. publish_request(...)                   → (ERE is idempotent; safe to re-publish)
4. wait on Event → canonical or provisional
```

#### Method: `resolve_bulk(entity_mentions: list[EntityMention]) -> list[Decision | CoordinatorException]`

```python
async def resolve_bulk(...):
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
        raise ResolutionTimeoutException("Bulk resolution exceeded client time budget")
```

`asyncio.gather` with `return_exceptions=True` returns when **all N tasks complete**.
Since each `resolve_single` handles its own ERE timeout internally (issuing provisional
on timeout), the gather returns naturally when every mention has a result. If the bulk
budget fires before all complete, `ResolutionTimeoutException` is raised.

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
from erspec.models.core import ClusterReference, Decision, EntityMention, EntityMentionIdentifier
from erspec.models.ere import EntityMentionResolutionRequest
from ers import config
from ers.commons.adapters.tracing import trace_function
from ers.ere_contract_client.domain.errors import RedisConnectionError
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.request_registry.services.exceptions import IdempotencyConflictError
from ers.rdf_mention_parser.domain.exceptions import (
    ContentTooLargeError, EmptyExtractionError, EntityTypeMismatchError,
    MalformedRDFError, MultipleEntitiesFoundError, UnsupportedEntityTypeError,
)
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService
from ers.resolution_decision_store.domain.errors import StaleOutcomeError
from ers.resolution_decision_store.adapters.provisional_id import derive_provisional_cluster_id
from ers.resolution_coordinator.domain.exceptions import (
    CoordinatorException, EnginePublishFailedException,
    ParsingFailedException, ResolutionTimeoutException,
)
from ers.resolution_coordinator.services.async_resolution_waiter import AsyncResolutionWaiter
```

Verify each import path exists before using it. Run
`poetry run python -c "from <path> import <name>"` for any uncertain ones.

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
| TC-005 | Idempotent — decision exists | `decision_svc.get_decision_by_triad` returns existing Decision | Existing `Decision`; `publish_request` NOT called; `waiter.get_or_create` NOT called |
| TC-006 | Idempotent — no decision yet | `get_decision_by_triad` returns None; ERE responds in time | Canonical Decision; `publish_request` called once |
| TC-007 | Idempotency conflict | `registry_svc.register_resolution_request` raises `IdempotencyConflictError` | `IdempotencyConflictError` propagated; `store_decision` NOT called |
| TC-008 | Parse failure — MalformedRDF | `register_resolution_request` raises `MalformedRDFError` | `ParsingFailedException` raised; `publish_request` NOT called |
| TC-009 | Parse failure — ContentTooLarge | `register_resolution_request` raises `ContentTooLargeError` | `ParsingFailedException` raised |
| TC-010 | Decision Store unavailable on provisional write | `store_decision` raises `RepositoryConnectionError` | `ResolutionTimeoutException` raised |
| TC-011 | Stale provisional write | `store_decision` raises `StaleOutcomeError`; `get_decision_by_triad` returns ERE decision | ERE `Decision` returned; no exception |
| TC-012 | Bulk — all succeed | 3 mentions; all ERE respond in time | List of 3 canonical Decisions in input order |
| TC-013 | Bulk — partial parse failure | 3 mentions; mention 2 malformed | List: [Decision, ParsingFailedException, Decision] |
| TC-014 | Bulk — partial ERE timeout | 3 mentions; mention 3 budget expires | List: [Decision, Decision, provisional Decision] |
| TC-015 | Bulk — empty input | `resolve_bulk([])` | Returns `[]` |
| TC-016 | Bulk — bulk budget exceeded | `BULK_REQUEST_TIME_BUDGET` monkeypatched to 0.01s; all mentions hang | `ResolutionTimeoutException` raised |
| TC-017 | `waiter.release` called on success | Happy path | `waiter.release` called exactly once |
| TC-018 | `waiter.release` called on ERE timeout | Budget expires path | `waiter.release` called exactly once |
| TC-019 | `waiter.release` called on Redis failure | Redis down path | `waiter.release` called exactly once |
| TC-020 | No waiter call on instant decision return | `get_decision_by_triad` returns decision immediately | `waiter.get_or_create` NOT called |

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
- [ ] All 20 unit tests pass: `poetry run pytest tests/unit/resolution_coordinator/services/test_resolution_coordinator_service.py -v`
- [ ] `waiter.release` always called in `finally` (verified by TC-017, TC-018, TC-019)
- [ ] `poetry run pylint src/ers/resolution_coordinator/services/resolution_coordinator_service.py` — no errors
- [ ] `poetry run pytest tests/unit/resolution_coordinator/ -v --cov=src/ers/resolution_coordinator --cov-report=term-missing` — coverage ≥ 90%
