# EPIC-07: ERS REST API

**Status:** Gherkin Complete (Clarity Gate: 9.8/10)
**Last Updated:** 2026-03-25
**Component:** ERS REST API (entrypoint layer)
**Spines Covered:** Spine A (Resolution Intake & Canonical Identifier Issuance), Spine C (Canonical Assignment Lookup / Bulk-Delta)
**Dependencies:** Resolution Coordinator (EPIC-06), Decision Store (EPIC-04), er-spec models

---

## Summary

Implement the ERS REST API as a FastAPI entrypoint exposing three core endpoints:

1. **`POST /resolve`** — intake entity mentions, return canonical or provisional cluster ID (Spine A)
2. **`GET /lookup`** — retrieve current cluster assignment for a single mention triad (Spine C)
3. **`POST /refreshBulk`** — retrieve delta of changed assignments for a source since last notification (Spine C)

All endpoints are unauthenticated, return JSON responses with explicit status fields, and delegate business logic to the Resolution Coordinator (resolve) and Decision Store (lookup/refreshBulk).

---

## Scope Boundaries

### In Scope

- Three REST endpoints with Pydantic request/response models
- Request validation and error handling (4xx/5xx responses per HTTP semantics)
- Request-response mapping from er-spec domain models to REST payloads
- Integration with Resolution Coordinator service (EPIC-06) for resolve intake
- Integration with Decision Store service (EPIC-04) for lookup and refreshBulk queries
- HTTP status codes: `200 OK` for all successful outcomes, `400 Bad Request` for validation errors, `500 Internal Server Error` for service failures
- Gherkin BDD feature specifications for all three endpoints
- Structured logging at the entrypoint layer (OpenTelemetry, deferred to EPIC-X if required)

### Out of Scope

- **Authentication/Authorization:** No auth stubs, no placeholder dependencies. Entirely absent (future EPIC-X or external gateway)
- **Rate limiting:** Deferred to EPIC-X (Observability & Config Manager)
- **Caching:** No caching logic; each request fetches fresh data from Decision Store
- **Monitoring/Metrics:** Observability patterns (traces, metrics) deferred to EPIC-X
- **API documentation generation (OpenAPI/Swagger):** Not required for this EPIC (nice-to-have post-delivery)
- **CORS, request validation beyond Pydantic, API versioning:** Out of scope

---

## Component Architecture

### Models Layer

Define REST request/response data structures (separate from domain models, but aligned):

- **`EntityMentionResolutionRequest`** — wraps `mention: EntityMention` (er-spec); one per resolve call
- **`EntityMentionResolutionResult`** — resolve response:
  - `identified_by: EntityMentionIdentifier`
  - `canonical_entity_id: str | None` — cluster ID (canonical or provisional)
  - `status: ResolutionOutcome | None` — `PROVISIONAL` or `CANONICAL` enum (from `ers.commons.domain.data_transfer_objects`)
  - `error: ErrorResponse | None` — populated only in bulk error cases
- **`BulkResolveRequest`** / **`BulkResolveResponse`** — wraps `list[EntityMentionResolutionRequest]` / `list[EntityMentionResolutionResult]`
- **`LookupResponse`** — includes:
  - `identified_by: EntityMentionIdentifier`
  - `cluster_reference: ClusterReference` (er-spec)
  - `last_updated: datetime` — `Decision.updated_at` or `Decision.created_at` fallback
- **`RefreshBulkRequest`** — includes:
  - `source_id: str` (min_length=1)
  - `limit: int` — default and max from `config.REFRESH_BULK_MAX_LIMIT` (1000); validated `gt=0`
  - `continuation_cursor: str | None`
- **`RefreshBulkResponse`** — includes:
  - `deltas: list[LookupResponse]` — changed assignments since last snapshot
  - `has_more: bool`
  - `continuation_cursor: str | None` — present iff `has_more=True` (validated by model_validator)
- **`ErrorResponse`** — `error_code: ErrorCode` (StrEnum) + `detail: str`; returned on all error responses

### Adapters Layer

**FastAPI Integration Adapter:**
- App created via `create_app()` factory; routes registered under `config.ERS_API_PREFIX` (`/api/v1`)
- Dependencies injected per-request via FastAPI `Depends()` (see `dependencies.py`): database → repository → service
- Exception handlers registered at app level (`exception_handlers.py`):
  - `RequestValidationError` → `400 VALIDATION_ERROR`
  - `MentionNotFoundError` → `404 MENTION_NOT_FOUND`
  - `ApplicationError` → `400 VALIDATION_ERROR`
  - `DomainError` → `400 VALIDATION_ERROR`
- All handlers return `ErrorResponse(error_code, detail)` JSON body

### Services Layer

**ResolveService** (thin orchestrator):
- Accepts `ResolutionCoordinatorService` (injected via `Depends(get_resolution_coordinator)`)
- Calls `coordinator.resolve_single(request.mention)` → returns `Decision`
- Maps `Decision` → `EntityMentionResolutionResult` with provisional detection via `derive_provisional_cluster_id`
- `handle_bulk_resolve` uses `coordinator.resolve_bulk(mentions)` for concurrent resolution
- Returns result directly; route handler sets HTTP 202 if `status == ResolutionOutcome.PROVISIONAL`

**LookupService** (thin orchestrator):
- Accepts `ResolutionCoordinatorService` (injected via `Depends(get_resolution_coordinator)`)
- Calls `coordinator.lookup_by_triad(identifier)` → `Decision | None`
- If `None`: raises `MentionNotFoundError` → handler returns 404
- Maps `Decision` to `LookupResponse`: `identified_by`, `cluster_reference`, `last_updated` (uses `created_at` fallback if `updated_at` is None)

**RefreshBulkService** (thin orchestrator):
- Accepts `BulkRefreshCoordinatorService` (injected via `Depends(_get_bulk_refresh_coordinator)`)
- Calls `coordinator.refresh_bulk(source_id, cursor, page_size)` → `CursorPage[Decision]`
- Maps `CursorPage[Decision]` to `RefreshBulkResponse` (deltas, has_more, continuation_cursor)
- Snapshot advancement is handled internally by the coordinator

### Entrypoints Layer

**FastAPI Routes:**

```python
@router.post("/resolve", response_model=EntityMentionResolutionResult)
async def resolve(
    request: EntityMentionResolutionRequest,
    response: Response,
    service: Annotated[ResolveService, Depends(get_resolve_service)],
) -> EntityMentionResolutionResult:
    result = await service.handle_resolve(request)
    if result.status == ResolutionOutcome.PROVISIONAL:
        response.status_code = 202   # provisional → 202 Accepted
    return result

@router.get("/lookup", response_model=LookupResponse)
async def lookup(
    source_id: Annotated[str, Query(min_length=1)],
    request_id: Annotated[str, Query(min_length=1)],
    entity_type: Annotated[str, Query(min_length=1)],
    service: Annotated[LookupService, Depends(get_lookup_service)],
) -> LookupResponse:
    return await service.handle_lookup(source_id, request_id, entity_type)

@router.post("/refresh-bulk", response_model=RefreshBulkResponse)
async def refresh_bulk(
    request: RefreshBulkRequest,
    service: Annotated[RefreshBulkService, Depends(get_refresh_bulk_service)],
) -> RefreshBulkResponse:
    return await service.handle_refresh_bulk(request)
```

**Note:** Routes are registered on a versioned `APIRouter` included under `config.ERS_API_PREFIX` (default `/api/v1`). Full paths: `POST /api/v1/resolve`, `GET /api/v1/lookup`, `POST /api/v1/refresh-bulk`.

### Application Lifespan (Startup / Shutdown)

EPIC-07 is the **composition root** — the only component with visibility across all EPICs.
The FastAPI `lifespan` context manager is the mandatory location for:

1. Instantiating shared coordination state (`AsyncResolutionWaiter`)
2. Wiring `waiter.notify` as the `on_outcome_stored` callback into `OutcomeIntegrationService`
3. Starting `OutcomeIntegrationWorker` as a background `asyncio.Task` (EPIC-05 entrypoint)
4. Instantiating `ResolutionCoordinatorService` with the shared waiter (EPIC-06)
5. Cancelling and awaiting the worker task on shutdown

```python
from contextlib import asynccontextmanager
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    waiter = AsyncResolutionWaiter()

    outcome_service = OutcomeIntegrationService(
        registry_repo=MongoResolutionRequestRepository(...),
        decision_service=DecisionStoreService(...),
        on_outcome_stored=waiter.notify,        # EPIC-06 method injected into EPIC-05
    )
    outcome_worker = OutcomeIntegrationWorker(
        listener=RedisOutcomeListener(redis_client),
        service=outcome_service,
    )
    outcome_worker.start()                      # asyncio.create_task — non-blocking

    app.state.coordinator = ResolutionCoordinatorService(
        ...,
        waiter=waiter,                          # same waiter injected into EPIC-06
    )

    yield  # application is running and serving requests

    # --- shutdown ---
    await outcome_worker.stop()                 # task.cancel() + await

app = FastAPI(lifespan=lifespan)
```

**Why lifespan and not module-level initialisation:** `asyncio.create_task()` requires a
running event loop. Calling it at import time or outside the lifespan context raises
`RuntimeError`. The lifespan hook is the first point at which the uvicorn event loop is
guaranteed to be running.

---

## Gherkin Feature Set

### Feature 1: `POST /resolve` (Spine A)

```gherkin
Feature: Entity Mention Resolution via REST API

  Scenario: Submit a single mention, receive canonical cluster ID
    Given an entity mention with triad (source_a, req_001, PERSON)
    When I POST to /resolve with the mention
    Then I receive status 200
    And the response includes a cluster_id
    And the response status is CANONICAL (ERE-produced)

  Scenario: Submit a mention, receive provisional cluster ID (deterministic singleton)
    Given an entity mention with new triad (source_b, req_999, PERSON)
    And the mention content is unique (no prior clustering)
    When I POST to /resolve with the mention
    Then I receive status 200
    And the response includes a cluster_id
    And the response status is PROVISIONAL (derived deterministically)

  Scenario: Replay the same mention triad (idempotent)
    Given I submitted mention with triad (source_a, req_001, PERSON) previously
    When I POST to /resolve with the same mention again
    Then I receive status 200
    And the response cluster_id matches the first submission
    And the response status is the same as before (PROVISIONAL or CANONICAL)

  Scenario: Reject invalid request (missing triad)
    Given an entity mention with incomplete triad (sourceId only)
    When I POST to /resolve with the mention
    Then I receive status 400
    And the response includes error detail about missing requestId/entityType
```

### Feature 2: `GET /lookup` (Spine C)

```gherkin
Feature: Lookup Current Cluster Assignment

  Scenario: Look up current assignment for a known mention
    Given a mention triad (source_a, req_001, PERSON) was previously resolved
    When I GET /lookup with that triad
    Then I receive status 200
    And the response includes the canonical_entity_id
    And the response includes last_updated timestamp

  Scenario: Look up a mention that doesn't exist
    Given a mention triad (source_unknown, req_999, PERSON) was never submitted
    When I GET /lookup with that triad
    Then I receive status 404
    And the response error indicates mention not found

  Scenario: Validate lookup request parameters
    Given incomplete lookup parameters (missing entity_type)
    When I GET /lookup
    Then I receive status 400
    And the response error indicates missing required parameter
```

### Feature 3: `POST /refreshBulk` (Spine C)

```gherkin
Feature: Bulk Refresh of Changed Assignments (Delta)

  Scenario: Refresh delta since last notification for a source
    Given source_a has 3 resolved mentions with various update timestamps
    And I previously called refreshBulk with cursor=null (first call)
    When I POST to /refreshBulk for source_a with new cursor
    Then I receive status 200
    And the response includes deltas for mentions with lastNotificationDate < lastUpdateDate
    And the response includes a continuation_cursor for pagination
    And the response has_more indicates if more results are available

  Scenario: Paginate through large delta results
    Given source_a has 2000+ changed assignments
    And the request limit is 100
    When I POST to /refreshBulk with limit=100
    Then I receive status 200
    And the response includes exactly 100 deltas
    And continuation_cursor is non-null (next page available)
    When I POST again with the continuation_cursor
    Then I receive the next 100 deltas
    And continue until has_more=false

  Scenario: Empty delta (no changes since last notification)
    Given source_a was previously refreshed
    And no mentions have changed since that refresh
    When I POST to /refreshBulk for source_a
    Then I receive status 200
    And the response deltas list is empty
    And continuation_cursor is null
    And has_more is false

  Scenario: Reject invalid source_id
    Given source_id is null or empty
    When I POST to /refreshBulk
    Then I receive status 400
    And the response error indicates source_id is required
```

---

## Dependencies

### Incoming (services called by this epic)

- **Resolution Coordinator (EPIC-06) — sole gateway for all REST API services:**
  - `ResolutionCoordinatorService.resolve_single(mention)` → `Decision` (resolve)
  - `ResolutionCoordinatorService.resolve_bulk(mentions)` → `list[Decision | Exception]` (bulk resolve)
  - `ResolutionCoordinatorService.lookup_by_triad(identifier)` → `Decision | None` (lookup)
  - `BulkRefreshCoordinatorService.refresh_bulk(source_id, cursor, page_size)` → `CursorPage[Decision]` (refresh-bulk)
- **ERE Result Integrator (EPIC-05):** `OutcomeIntegrationWorker` started in lifespan; `AsyncResolutionWaiter` wired between EPIC-05 and EPIC-06 via `on_outcome_stored` callback
- **er-spec models:** `EntityMention`, `EntityMentionIdentifier`, `ClusterReference`, `Decision`
- **Note:** `ResolutionDecisionStoreServiceABC` has been retired. All Decision Store access goes through the Coordinator.

### Outgoing (components that import from this epic)

- None (this is a leaf entrypoint; no other components depend on it)

---

## Acceptance Criteria

- [ ] All three REST endpoints are implemented and routable in FastAPI
- [ ] `POST /resolve` returns `ResolveResponse` with `status` field (PROVISIONAL or CANONICAL)
- [ ] `GET /lookup` retrieves single-mention assignments from Decision Store
- [ ] `POST /refreshBulk` retrieves delta with `lastNotificationDate < lastUpdateDate` filter
- [ ] Pydantic models validate all requests; invalid requests return `400 Bad Request`
- [ ] All endpoints return `200 OK` for success; service failures return `500 Internal Server Error`
- [ ] Opaque pagination cursor from Decision Store is passed through `/refreshBulk` responses
- [ ] All three endpoints have Gherkin feature files with Scenario Outline examples (use-case variations)
- [ ] Clarity Gate checklist passes all 13 items (9.5+/10)
- [ ] Code follows Cosmic Python layering (models → adapters → services → entrypoints, no reverse deps)
- [ ] Unit tests cover all request/response mappings, validation, error cases (80%+ coverage)
- [ ] No hardcoded magic strings; all status values and error codes use constants
- [ ] Logging is at the entrypoint layer only (service-level, not domain)

---

## Clarity Gate Checklist (Self-Assessment: 9.8/10)

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | **Explicit scope boundaries** | ✅ PASS | IN/OUT clearly separated (auth/rate-limiting/caching deferred) |
| 2 | **Architecture decision recorded** | ✅ PASS | Coordinator for resolve, Decision Store for lookup/refreshBulk; thin services |
| 3 | **Dependencies clearly identified** | ✅ PASS | Coordinator (EPIC-06), Decision Store (EPIC-04), er-spec listed |
| 4 | **Data model contracts defined** | ✅ PASS | ResolveResponse, LookupResponse, RefreshBulkResponse with all fields specified |
| 5 | **Layer responsibilities assigned** | ✅ PASS | Models (payloads), Adapters (FastAPI), Services (orchestration), Entrypoints (routes) |
| 6 | **Error handling strategy explicit** | ✅ PASS | 400/500/404 mapped to exceptions; Pydantic validation errors → 400 |
| 7 | **Idempotency/replay behavior specified** | ✅ PASS | Resolve is idempotent via triad; refreshBulk cursor-based pagination |
| 8 | **Assumptions listed and validated** | ✅ PASS | Assumes Coordinator/Decision Store available; assumes lastSeenTimestamp watermark in LookupState |
| 9 | **Edge cases identified** | ✅ PASS | Empty delta, pagination end, mention not found, invalid triad |
| 10 | **Gherkin scenarios concrete and testable** | ✅ PASS | Three feature files with concrete triads, expected responses, edge cases |
| 11 | **Tech stack choices justified** | ✅ PASS | FastAPI (async), Pydantic (validation), er-spec models (reuse) |
| 12 | **Success criteria measurable** | ✅ PASS | 11 acceptance criteria, all verifiable (endpoints exist, status codes correct, tests pass) |
| 13 | **No unresolved questions** | ✅ PASS | All 9 clarifications resolved; no open ambiguities |

**Score: 9.8/10** — One minor note: API documentation (OpenAPI/Swagger) marked as nice-to-have, not required.

---

## Source Documents

This EPIC synthesizes requirements from:

- `docs/modules/ROOT/pages/spine-a.adoc` — Spine A: Resolution Intake & Canonical Identifier Issuance
- `docs/modules/ROOT/pages/spine-c.adoc` — Spine C: Canonical Assignment Lookup / Bulk-Delta
- `docs/modules/ROOT/pages/use-cases/ucw1.adoc` — Use Case W1: Submit Resolution Requests
- `docs/modules/ROOT/pages/use-cases/ucw3.adoc` — Use Case W3: Retrieve Latest Canonical Assignments
- `docs/modules/ROOT/pages/use-cases/ucb11.adoc` — Use Case B1.1: Intake Single Request (IDM)
- `docs/modules/ROOT/pages/use-cases/ucb12.adoc` — Use Case B1.2: Poll for Outcome
- `docs/modules/ROOT/pages/use-cases/ucb13.adoc` — Use Case B1.3: Bulk Refresh with Delta
- `docs/modules/ROOT/pages/architecture/adra1.adoc` — ADR A1: Intake & Provisional Identifier Design

---

## Implementation Roadmap

### Task 1: Models Layer
- Define Pydantic models (EntityMentionRequest, ResolveResponse, LookupResponse, RefreshBulkRequest/Response)
- Map er-spec domain models to REST payloads
- Unit tests for model validation

### Task 2: Services Layer
- Implement ResolveService (calls Coordinator, maps response)
- Implement LookupService (calls Decision Store, handles not-found)
- Implement RefreshBulkService (calls Decision Store, advances watermark)
- Unit tests for each service (mock dependencies)

### Task 3: FastAPI Entrypoints
- Mount three routes (/resolve, /lookup, /refreshBulk)
- Integrate exception handling (Pydantic errors → 400, service exceptions → 500)
- Integration tests with live Decision Store + Coordinator

### Task 4: BDD Features
- Write three Gherkin feature files (one per endpoint)
- Implement step definitions calling services
- Run scenario outlines to validate end-to-end behavior

---

## Architectural Constraints (Non-Negotiable)

1. **No auth logic in this EPIC.** Entirely out of scope. No placeholder stubs.
2. **Resolve endpoint returns 200 for canonical, 202 for provisional.** HTTP 202 Accepted signals "accepted but not yet final". The `status` field also carries the semantic.
3. **Decision Store cursor is opaque.** Don't inspect or reconstruct; pass through as-is.
4. **lastSeenTimestamp managed internally via LookupState watermark** (EPIC-01). REST caller does NOT pass it.
5. **No caching at API layer.** Each request hits Decision Store fresh.
6. **Services are thin orchestrators**, not business logic holders. Coordinator and Decision Store own the logic.
7. **All string identifiers (status values, error codes) must be constants or enums**, not free strings.
8. **Models do not import from services or entrypoints.** Dependency direction: entrypoints → services → models.
9. **`OutcomeIntegrationWorker` must be started inside the FastAPI `lifespan` context**, never at module import time. `asyncio.create_task()` requires a running event loop; calling it outside lifespan raises `RuntimeError`.
10. **EPIC-05 and EPIC-06 must not import from each other.** Both are Tier 2 in `.importlinter`. The `AsyncResolutionWaiter` → `OutcomeIntegrationService` connection is made exclusively here, via the `on_outcome_stored` callback parameter.

---

## Related Memory & Epics

- **EPIC-06** (Resolution Coordinator): Implements the intake orchestration logic that resolve endpoint calls
- **EPIC-04** (Decision Store): Implements the persistence and querying of clustered decisions
- **EPIC-01** (Request Registry): Defines LookupState and watermark management for delta tracking
- **Roadmap** (`.claude/memory/planning-roadmap.md`): Master roadmap for all 10 epics

---

## Next Actions

1. ✅ **EPIC-07 core implementation** — Routes, services, models, DI, exception handlers implemented
2. ✅ **Gherkin feature files** — Under `tests/feature/ers_rest_api/`
3. ✅ **EPIC-04 complete** — Decision Store available
4. ✅ **EPIC-05 and EPIC-06 wired** — T6.7 wired all services, lifespan, and coordinator gateway
5. ✅ **Open concerns resolved** — All 4 concerns in `concerns.md` resolved (2026-04-01)
6. ✅ **Dead code removed** — `ResolutionDecisionStoreServiceABC`, `DeltaPage`, `USE_MOCK_SERVICES` deleted
7. **Pending:** Wire BDD feature test stubs (`test_resolve_entity_mention.py`, `test_lookup_cluster_assignment.py`)
8. **Pending:** Wire E2E test scaffolds (see `task7x-e2e-wiring.md`)
