# Task 6.6 — Integration + Feature Tests

## Goal

Wire all scaffolded step-definition TODOs to real service calls, and write integration
tests that exercise the full stack with real MongoDB and Redis. This is the
validation gate for Tasks 6.1–6.5 working together.

---

## Scope

### Part A — Gherkin feature step definitions (BDD wiring)

Four feature files exist with fully scaffolded `assert True  # TODO` stubs.
Wire each stub to call the real services. No new feature files needed.

#### `tests/feature/resolution_coordinator/test_single_mention_resolution.py`

Wire against `ResolutionCoordinatorService` with mocked dependency services
(same as unit tests — BDD tests at this level use mocks to stay fast and isolated).

Key wiring decisions:
- `Background`: construct a real `ResolutionCoordinatorService` with `AsyncMock` dependencies
  and a real `AsyncResolutionWaiter`. Store in `ctx["service"]`.
- ERE response simulation: `asyncio.create_task` that calls `waiter.notify(triad_key)`
  after a short sleep (0.05s).
- Provisional path: do NOT call notify — let `SINGLE_REQUEST_TIME_BUDGET` expire
  (monkeypatch it to 0.1s for test speed).
- All `Then` steps assert against `ctx["result"]` or `ctx["raised_exception"]`.

#### `tests/feature/resolution_coordinator/test_async_resolution_waiter.py`

Wire against a real `AsyncResolutionWaiter` instance. No mocks needed.
Use `asyncio.gather` and `asyncio.create_task` to simulate concurrent waiters.
Timeout scenarios use `asyncio.wait_for` with short timeouts (0.05s).

#### `tests/feature/resolution_coordinator/test_bulk_resolution.py`

Wire against `ResolutionCoordinatorService` with mocked dependencies.
Simulate different per-mention outcomes by configuring `AsyncMock.side_effect`
as a list keyed to call order.

#### `tests/feature/resolution_coordinator/test_bulk_lookup.py`

Wire against `BulkRefreshCoordinatorService` with mocked dependencies.
`source_has_requests` side_effect controls known vs unknown source scenarios.

---

### Part B — Integration tests

File: `tests/integration/resolution_coordinator/test_resolution_coordinator_integration.py`

These tests run against **real MongoDB and real Redis** via testcontainers (or the
project's existing docker-compose test infrastructure — check how other integration
tests in `tests/integration/` are set up and follow the same pattern exactly).

Mark all tests with `@pytest.mark.integration` so they can be skipped in environments
without infrastructure:
```python
pytestmark = pytest.mark.integration
```

#### Test infrastructure

Reuse the project's existing MongoDB and Redis fixtures if they exist in
`tests/integration/conftest.py` or a shared integration conftest. Do not create
duplicate infrastructure code.

Wire real instances of all dependency services:
```
MongoResolutionRequestRepository → RequestRegistryService
MongoDecisionRepository          → DecisionStoreService
Redis AbstractClient             → EREPublishService
AsyncResolutionWaiter            (in-process, no infra needed)
ResolutionCoordinatorService     (wires everything above)
BulkRefreshCoordinatorService    (wires registry + decision store)
```

ERE response simulation: instead of a real ERE engine, simulate EPIC-05 by
calling `waiter.notify(triad_key)` from a background task after the test
publishes a request — the same pattern used in the e2e tests.

#### Integration scenarios to cover

| IT | Scenario | Infrastructure | Verification |
|----|----------|----------------|--------------|
| IT-001 | Full happy path | MongoDB + Redis | Submit mention → notify waiter → canonical Decision returned and persisted |
| IT-002 | Timeout → provisional | MongoDB + Redis; no notify | Submit mention → `SINGLE_REQUEST_TIME_BUDGET` expires → provisional Decision returned and persisted in MongoDB |
| IT-003 | Redis down → provisional | MongoDB only; Redis not available | Submit mention → `RedisConnectionError` → provisional returned and persisted |
| IT-004 | Idempotent replay — decision exists | MongoDB + Redis; pre-seed Decision | Same triad+content → existing Decision returned; no new ERE publish |
| IT-005 | Concurrent identical requests | MongoDB + Redis | 5 coroutines submit same triad concurrently → all 5 return same Decision; exactly 1 Redis push |
| IT-006 | Bulk decomposition | MongoDB + Redis | Submit 3 mentions → notify all 3 waiters → 3 independent Decisions returned in order |
| IT-007 | Bulk refresh — delta | MongoDB | Pre-seed 5 Decisions for source; 3 updated after snapshot → delta returns 3 |
| IT-008 | Bulk refresh — first lookup | MongoDB | No prior snapshot → all decisions for source returned |
| IT-009 | Bulk refresh — unknown source | MongoDB | Source has no requests → `SourceNotFoundException` |

IT-005 (concurrent identical requests) is the most complex test. Pattern:
```python
async def test_concurrent_identical_requests(coordinator, waiter):
    triad_key = "SYSTEM_Areq-005Organization"
    mention   = make_entity_mention("SYSTEM_A", "req-005")

    # Start 5 concurrent resolve_single calls
    tasks = [asyncio.create_task(coordinator.resolve_single(mention))
             for _ in range(5)]

    # Give all tasks time to register and start waiting
    await asyncio.sleep(0.05)

    # Simulate exactly one ERE response
    await waiter.notify(triad_key)

    results = await asyncio.gather(*tasks)

    # All 5 should return the same decision
    cluster_ids = {r.current_placement.cluster_id for r in results}
    assert len(cluster_ids) == 1

    # Exactly one ERE publish occurred
    # (check Redis list length or mock the publish count)
```

---

## asyncio test isolation

When tests run concurrently (e.g. with `pytest-xdist`) or share an event loop,
leftover tasks from one test can affect another. Ensure:

1. Each test function creates a fresh `AsyncResolutionWaiter` instance — do NOT share
   a module-level waiter across tests.
2. Use `pytest-asyncio`'s `event_loop` fixture scope appropriate to the project setup.
3. Any `asyncio.create_task` background tasks should be explicitly awaited or
   cancelled in teardown to avoid warnings.
4. For integration tests, flush Redis between tests using the fixture teardown
   (same pattern as the existing integration tests).

---

## Files to Create / Modify

| Action | File |
|--------|------|
| Modify | `tests/feature/resolution_coordinator/test_single_mention_resolution.py` |
| Modify | `tests/feature/resolution_coordinator/test_async_resolution_waiter.py` |
| Modify | `tests/feature/resolution_coordinator/test_bulk_resolution.py` |
| Modify | `tests/feature/resolution_coordinator/test_bulk_lookup.py` |
| Create | `tests/integration/resolution_coordinator/__init__.py` |
| Create | `tests/integration/resolution_coordinator/test_resolution_coordinator_integration.py` |

---

## Definition of Done

- [ ] All 4 feature files pass with real service calls (no `assert True` stubs remain):
  `poetry run pytest tests/feature/resolution_coordinator/ -v`
- [ ] All 9 integration tests pass (requires MongoDB + Redis):
  `poetry run pytest tests/integration/resolution_coordinator/ -v -m integration`
- [ ] Integration tests are skippable without infrastructure:
  `poetry run pytest tests/integration/resolution_coordinator/ -v -m "not integration"` — 0 collected
- [ ] No leftover background tasks or event loop warnings in test output
- [ ] `poetry run pytest tests/unit/resolution_coordinator/ tests/feature/resolution_coordinator/ -v --cov=src/ers/resolution_coordinator --cov-report=term-missing` — coverage ≥ 90%
