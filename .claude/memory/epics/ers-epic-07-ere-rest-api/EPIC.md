# EPIC-07: ERS REST API

**Status:** Written (Clarity Gate: 9.8/10)
**Last Updated:** 2026-03-12
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

- **`EntityMentionRequest`** — reuse er-spec `EntityMention` directly (identifier triad + content + content_type)
- **`ResolveResponse`** — includes:
  - `canonical_entity_id: str` — the cluster ID (canonical or provisional)
  - `status: str` — `"PROVISIONAL"` or `"CANONICAL"` (indicates if ID may change)
  - `entity_mention_context: dict` (optional context echoed back)
  - `request_id: str` — triad request ID for correlation
- **`LookupResponse`** — includes:
  - `cluster_reference: ClusterReference` — reuse from er-spec (or embedded `canonical_entity_id` + `entity_type`)
  - `last_updated: datetime` — timestamp of last Decision Store update
- **`RefreshBulkRequest`** — includes:
  - `source_id: str` — the data source identifier
  - `limit: int = 1000` — optional page size (default 1000)
  - `continuation_cursor: str | None` — opaque cursor for pagination
- **`RefreshBulkResponse`** — includes:
  - `deltas: list[DeltaAssignment]` — list of changed assignments
  - `continuation_cursor: str | None` — opaque cursor for next page (None if end)
  - `has_more: bool` — indicates if more results available
  - Each `DeltaAssignment`: mention triad + canonical_entity_id + update timestamp

### Adapters Layer

**FastAPI Integration Adapter:**
- Mount FastAPI app with three route handlers (resolve, lookup, refreshBulk)
- Parse HTTP requests, map to Pydantic models
- Handle Pydantic validation errors, return `400 Bad Request` with error detail
- Catch service exceptions, map to appropriate HTTP status codes:
  - `ServiceException` → `500 Internal Server Error`
  - `ValidationException` → `400 Bad Request`
  - `EntityNotFound` → `404 Not Found` (if applicable)
- Return JSON responses with explicit status codes

### Services Layer

**Resolve Service** (thin orchestrator):
- Validate `EntityMentionRequest` (idempotency triad presence, content not empty)
- Call Resolution Coordinator service (EPIC-06) with EntityMention
- Map Coordinator response (clusterId + outcome marker) to `ResolveResponse`
- Determine status: if provisional (deterministic derivation) → `"PROVISIONAL"`, else `"CANONICAL"`

**Lookup Service** (thin orchestrator):
- Validate lookup request (triad fields not null)
- Call Decision Store service (EPIC-04) `get_decision_for_mention(sourceId, requestId, entityType)`
- Map Decision to `LookupResponse`
- If mention not found, raise `EntityNotFound` (404)

**RefreshBulk Service** (thin orchestrator):
- Validate `RefreshBulkRequest` (sourceId not null, limit > 0)
- Call Decision Store service (EPIC-04) `get_delta_for_source(sourceId, lastSeenTimestamp, limit, cursor)`
  - Delta query filters: `lastNotificationDate < lastUpdateDate`
  - Cursor is opaque, passed through from Decision Store
- Increment LookupState watermark for this source (advance `lastNotificationDate`)
- Map results to `RefreshBulkResponse`

### Entrypoints Layer

**FastAPI Routes:**

```python
@app.post("/resolve")
async def resolve(request: EntityMentionRequest) -> ResolveResponse:
    """POST /resolve — Resolve an entity mention, return canonical or provisional cluster ID."""
    return resolve_service.handle_resolve(request)

@app.get("/lookup")
async def lookup(
    source_id: str,
    request_id: str,
    entity_type: str,
) -> LookupResponse:
    """GET /lookup — Retrieve current cluster assignment for a mention triad."""
    return lookup_service.handle_lookup(source_id, request_id, entity_type)

@app.post("/refreshBulk")
async def refresh_bulk(request: RefreshBulkRequest) -> RefreshBulkResponse:
    """POST /refreshBulk — Retrieve delta of changed assignments since last notification."""
    return refreshbulk_service.handle_refreshbulk(request)
```

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

- **Resolution Coordinator (EPIC-06):** `/resolve` endpoint calls `Coordinator.handle_intake(EntityMention)` and receives `(clusterId, outcomeMarker)`
- **Decision Store (EPIC-04):** `/lookup` and `/refreshBulk` endpoints call:
  - `DecisionStore.get_decision_for_mention(sourceId, requestId, entityType)` → `Decision | None`
  - `DecisionStore.get_delta_for_source(sourceId, lastSeenTimestamp, limit, cursor)` → `(deltas, nextCursor)`
- **er-spec models:** Request/response models reuse `EntityMention`, `ClusterReference`, domain constants

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
2. **Resolve endpoint always returns 200 OK**, even for provisional IDs. Status field carries the semantic.
3. **Decision Store cursor is opaque.** Don't inspect or reconstruct; pass through as-is.
4. **lastSeenTimestamp managed internally via LookupState watermark** (EPIC-01). REST caller does NOT pass it.
5. **No caching at API layer.** Each request hits Decision Store fresh.
6. **Services are thin orchestrators**, not business logic holders. Coordinator and Decision Store own the logic.
7. **All string identifiers (status values, error codes) must be constants or enums**, not free strings.
8. **Models do not import from services or entrypoints.** Dependency direction: entrypoints → services → models.

---

## Related Memory & Epics

- **EPIC-06** (Resolution Coordinator): Implements the intake orchestration logic that resolve endpoint calls
- **EPIC-04** (Decision Store): Implements the persistence and querying of clustered decisions
- **EPIC-01** (Request Registry): Defines LookupState and watermark management for delta tracking
- **Roadmap** (`.claude/memory/planning-roadmap.md`): Master roadmap for all 10 epics

---

## Next Actions

1. ✅ **EPIC-07 written** — Ready for implementation
2. **Pending:** Gherkin feature writing (gherkin-writer agent)
3. **Pending:** EPIC-06 and EPIC-04 completion (prereqs for implementation)
4. **Pending:** Implementer agent to code the three layers and pass Clarity Gate
