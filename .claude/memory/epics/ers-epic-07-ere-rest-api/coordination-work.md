# EPIC-07 — Coordination Work (EPIC-05 / EPIC-06 Wiring)
**Date:** 2026-03-25
**Scope:** New work in EPIC-07 required to complete the EPIC-05/06/07 communication plan
**Prerequisite:** EPIC-05 and EPIC-06 implementation must be complete first

This file describes what EPIC-07 must add once EPIC-05 (ERE Result Integrator) and
EPIC-06 (Resolution Coordinator) are implemented. The core API routes and services
are already working — this work wires the asynchronous background processing.

---

## Background — Why EPIC-07 owns this wiring

EPIC-07 is the **composition root** of the entire application. It is the only component
with visibility across all EPICs simultaneously. EPIC-05 and EPIC-06 must NOT import
from each other (both are Tier 2; `.importlinter` forbids same-tier sibling imports).
EPIC-07 connects them at runtime by:

1. Creating the shared `AsyncResolutionWaiter`
2. Passing `waiter.notify` as a callback into EPIC-05's service
3. Passing the waiter itself into EPIC-06's coordinator
4. Starting the EPIC-05 background worker as an asyncio Task

---

## WORK-01 — Extend the FastAPI lifespan context manager

**File:** `src/ers/ers_rest_api/entrypoints/api/app.py`

The current lifespan only manages the MongoDB connection. It must be extended to:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # --- existing: MongoDB ---
    manager = MongoClientManager(config.MONGO_URI, config.MONGO_DATABASE_NAME)
    await manager.connect()
    app.state.mongo_db = manager.get_database()

    # --- new: EPIC-05 / EPIC-06 coordination ---
    waiter = AsyncResolutionWaiter()

    outcome_service = OutcomeIntegrationService(
        registry_repo=MongoResolutionRequestRepository(app.state.mongo_db),
        decision_service=DecisionStoreService(
            MongoDecisionRepository(app.state.mongo_db)
        ),
        on_outcome_stored=waiter.notify,        # callback — no direct EPIC-05 → EPIC-06 import
    )
    outcome_worker = OutcomeIntegrationWorker(
        listener=RedisOutcomeListener(
            RedisEREClient(RedisConnectionConfig.from_settings(config))
        ),
        service=outcome_service,
    )
    outcome_worker.start()                      # asyncio.create_task — non-blocking

    coordinator = ResolutionCoordinatorService(
        registry_service=RequestRegistryService(...),
        parser_service=RDFMentionParserService(...),
        ere_publish_service=EREPublishService(...),
        decision_store_service=DecisionStoreService(...),
        waiter=waiter,
        config=CoordinatorConfig(),
    )
    app.state.coordinator = coordinator
    app.state.waiter = waiter

    yield  # application serving requests

    # --- shutdown ---
    await outcome_worker.stop()                 # task.cancel() + await
    await manager.close()
```

**Key constraint:** `asyncio.create_task()` must be called inside the lifespan context,
never at module import time — the event loop is not running until lifespan executes.

---

## WORK-02 — Update `get_resolution_coordinator` dependency provider

**File:** `src/ers/ers_rest_api/entrypoints/api/dependencies.py`

Current implementation raises `NotImplementedError`. Replace with actual wiring:

```python
async def get_resolution_coordinator(
    request: Request,
) -> ResolutionCoordinatorServiceABC:
    """Retrieve the ResolutionCoordinatorService from app state.
    Populated during lifespan startup once EPIC-06 is implemented.
    """
    return request.app.state.coordinator
```

The coordinator is created once in lifespan (stateful — holds the `AsyncResolutionWaiter`).
It must NOT be created fresh per request, unlike repositories.

---

## WORK-03 — Update `get_decision_store` dependency provider

**File:** `src/ers/ers_rest_api/entrypoints/api/dependencies.py`

Current implementation raises `NotImplementedError`. Once EPIC-04 `DecisionStoreService`
is confirmed to implement `ResolutionDecisionStoreServiceABC`, replace with:

```python
async def get_decision_store(
    decision_repository: Annotated[BaseDecisionRepository, Depends(get_decision_repository)],
) -> ResolutionDecisionStoreServiceABC:
    return DecisionStoreService(repository=decision_repository)
```

**Note:** This is a stateless service (repository injected per request) — unlike the
coordinator, it can be created per request.

**Dependency:** Resolve CONCERN-02 first (`get_lookup_state`/`advance_snapshot` ownership)
to confirm the correct constructor and injected dependencies.

---

## WORK-04 — Add exception handlers for EPIC-06 error types

**File:** `src/ers/ers_rest_api/entrypoints/api/exception_handlers.py`

Once EPIC-06 is implemented, verify that `CoordinatorError` and its subclasses are
handled correctly. Specifically:

| Exception | Target HTTP | Handler needed? |
|-----------|-------------|-----------------|
| `ResolutionTimeoutError` | 504 Gateway Timeout | Yes — not covered by current handlers |
| `ParsingFailedError` | 400 Bad Request | Likely covered if subclasses `ApplicationError` — verify |
| `IdempotencyConflictError` | 422 Unprocessable Entity | Currently maps to 400 via `ApplicationError` — consider dedicated handler |

```python
@app.exception_handler(ResolutionTimeoutError)
async def timeout_handler(request: Request, exc: ResolutionTimeoutError) -> JSONResponse:
    return JSONResponse(
        status_code=504,
        content={"error_code": "SERVICE_ERROR", "detail": exc.message},
    )
```

---

## WORK-05 — Integration tests for the full coordination flow

**Location:** `tests/integration/test_coordination_flow.py` (new file)

Once EPIC-05 and EPIC-06 are wired, add integration tests covering:

| Test | Description |
|------|-------------|
| `test_resolve_returns_canonical_when_ere_responds` | Worker receives ERE response → event fires → Coordinator returns `CANONICAL` |
| `test_resolve_returns_provisional_on_ere_timeout` | ERE does not respond within window → Coordinator returns `PROVISIONAL` (202) |
| `test_unsolicited_ere_update_reflected_in_lookup` | Worker receives `ereNotification:` → Decision Store updated → `/lookup` returns new cluster |
| `test_bulk_resolve_all_mentions_wired` | Multiple mentions → all processed concurrently via `asyncio.gather` |

**Infrastructure:** These tests require MongoDB + Redis running (testcontainers or docker-compose).
ERE responses are simulated by directly pushing to the `ere_responses` Redis channel.

---

## Dependency Order

```
EPIC-05 implementation complete
  ↓
EPIC-06 implementation complete
  ↓
Resolve CONCERN-01 (import violation check)
Resolve CONCERN-02 (lookup_state ownership)
Resolve CONCERN-03 (200 vs 202)
  ↓
WORK-01: Extend lifespan
WORK-02: Fix coordinator provider
WORK-03: Fix decision store provider
WORK-04: Add EPIC-06 exception handlers
  ↓
WORK-05: Integration tests
```
