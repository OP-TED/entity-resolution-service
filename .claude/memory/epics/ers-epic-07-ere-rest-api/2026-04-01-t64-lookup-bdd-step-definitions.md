# Task T6.4 — Lookup BDD Step Definitions

## Part 1: Task Specification

**Task description:** Rewrite the lookup cluster assignment BDD tests — update the `.feature` file to match the actual REST API implementation and wire all step definitions with real `httpx.AsyncClient` calls.

**Acceptance criteria:**
- Feature file uses correct routes (`/api/v1/lookup`, `/api/v1/refresh-bulk`)
- Response shape assertions use `cluster_reference.cluster_id` (not `canonical_entity_id`)
- Delta shape assertions use `identified_by`, `cluster_reference`, `last_updated`
- All step definitions make real HTTP calls via `httpx.AsyncClient`
- No `assert True  # TODO` remaining
- No `ctx["response"] = None  # TODO` remaining
- All 23 BDD scenarios pass
- No regressions in other feature or unit tests

**Gherkin scenarios covered:**
- Outline: Look up current assignment for a known mention (3 rows)
- Return not found when the mention triad is unknown
- Outline: Reject single lookup with missing or empty query parameters (6 rows)
- Outline: Retrieve changed assignments since the last synchronisation snapshot (3 rows)
- First bulk lookup for a source returns all assignments
- Page through a large delta set until exhausted
- Default page size is applied when limit is omitted
- Outline: Reject bulk lookup with invalid request fields (4 rows)
- Return service error when Decision Store is unavailable for single lookup
- Return service error on bulk lookup
- Lookup operations do not modify assignments or trigger resolution

**Layers affected:** tests only (feature + conftest)

---
<!-- implementation-log -->
---

## Part 2: Implementation Log

**Outcome:** All 23 BDD scenarios pass. No regressions (273/273 feature tests pass, 60/60 unit tests pass for ers_rest_api).

**Key decisions:**

1. **Shared conftest at `tests/feature/ers_rest_api/conftest.py`** — Created to hold background Given steps (`the ERS REST API is running`, `the Decision Store is available`), the `ctx` fixture, and common Then steps (HTTP status, error code, error message, error detail). The `test_resolve_entity_mention.py` was already rewritten in a previous session with its own local `ctx` and `@given("the ERS REST API is running")`; pytest-bdd 8.x lets local definitions override conftest definitions correctly, so no conflict arises.

2. **`raise_app_exceptions=False` for 500 scenarios** — Starlette's `ServerErrorMiddleware` re-raises `RuntimeError` through the ASGI transport before FastAPI's `@app.exception_handler(Exception)` can convert it to a 500 response. `ASGITransport(raise_app_exceptions=False)` makes the transport return the 500 JSON response instead of propagating the exception. The service-error Given steps rebuild `ctx["client"]` with this flag when they configure a `RuntimeError` side effect.

3. **`has_more` encoded in Given step** — The original scenario outline had separate `total_mentions` and `changed_count` columns. Simplified to a single step `source X has N changed assignments to return with has_more Y`, which directly encodes what the service mock returns. This avoids any ambiguity about how the service decides pagination.

4. **`side_effect` list for pagination walk** — The three-page pagination scenario uses `AsyncMock(side_effect=[page1, page2, page3])` so consecutive calls to `handle_refresh_bulk` return successive pages.

5. **Feature file simplifications** — Removed snapshot-advancement assertions (`the synchronisation snapshot for X is advanced`) because we mock at the service level and cannot verify coordinator internals. The read-only contract scenario was simplified to assert `resolve_service.handle_resolve.assert_not_called()`.

**Deviations from original spec:**
- Step `the synchronisation snapshot for X is advanced/not modified` removed — cannot verify coordinator internals through service mock. Coordinator snapshot behavior is already tested in `tests/feature/resolution_coordinator/test_bulk_lookup.py`.
- Original scenario outline used `total_mentions` + `changed_count`; simplified to a single `changed_count with has_more` parameter that directly drives the mock.
- "each delta includes canonical_entity_id, source_id, request_id, entity_type, and update timestamp" updated to "each delta has identified_by, cluster_reference, and last_updated fields" to match actual domain DTO shape.

**Files changed:**
- `tests/feature/ers_rest_api/lookup_cluster_assignment.feature` — updated routes, field names, simplified assertions
- `tests/feature/ers_rest_api/test_lookup_cluster_assignment.py` — full rewrite with real HTTP calls
- `tests/feature/ers_rest_api/conftest.py` — new file: shared fixtures and step definitions
- `tests/feature/ers_rest_api/test_resolve_entity_mention.py` — removed duplicate step definitions (already rewritten in prior session; this session only removed the stubs it had introduced)
