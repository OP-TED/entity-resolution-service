# Phase 5 — `?reviewed=true|false` filter on `/api/v1/curation/decisions`

## Task Specification

**Goal:** Add an optional boolean query parameter `reviewed` to the decision list
endpoint that filters decisions by current-placement review state.

**Semantic predicate:**
- `reviewed=true`: decision has a `user_action` with `created_at > (updated_at or created_at)`
- `reviewed=false`: no such action exists (Pending)
- `reviewed=None` (omitted): no filter — pipeline unchanged

**Layers affected:** entrypoints, services, adapters (repository)

**Constraints:**
- No DTO enum, no field on `DecisionSummary`, no new domain type.
- `reviewed` is plumbed as a service-layer kwarg, NOT added to `DecisionFilters`.
- Bulk-sync caller (`query_decisions_paginated`) must remain byte-identical in output.
- `$lookup` gated — only injected when `reviewed is not None`.

**Acceptance criteria:**
1. `reviewed=None` → `find()` path, no `$lookup` against `user_actions`.
2. `reviewed=True` → aggregation pipeline with `$lookup` + `$match {$ne: []}`.
3. `reviewed=False` → aggregation pipeline with `$lookup` + `$match {$eq: []}`.
4. `_has_recent_action` projected out of results.
5. Bulk-sync call (`filters=None`, no `reviewed`) continues to use `find()`.
6. Pagination (cursor + limit) works with both paths.

**Gherkin scenarios added** (appended to `decision_browsing.feature`):
- List decisions pending review
- Filter decisions already reviewed
- ERE re-integration returns to Pending
- Omitting reviewed leaves result set unchanged

---
<!-- implementation-log -->
---

## Implementation Log

### Accomplished

All 5 unit tests (repository pipeline verification) and 4 new BDD scenarios pass.
Existing 35 repository unit tests and 21 browsing BDD scenarios continue to pass.
Pre-existing test failures (27 curation service, 15 decision_store_service — async
decorator issues) were not introduced by this phase.

### Key decisions

**`reviewed` as keyword-only kwarg, not in `DecisionFilters`:** `DecisionFilters`
lives in `commons` and is shared by both the curation path and the bulk-sync path.
Adding `reviewed` there would pollute the shared contract and risk inadvertent use
in the bulk-sync path. A separate kwarg keeps the two paths cleanly separated.

**`_fetch_with_review_filter` as a private helper:** The reviewed aggregation branch
is materially different from the `find()` path (different MongoDB API, 6-stage
pipeline). Extracting it into a dedicated method keeps `find_with_filters` readable
and testable at the correct granularity.

**`$limit` before `$lookup`:** The pipeline applies `$sort` then `$limit` before the
`$lookup` so the correlated join is performed only on the page slice, not the full
collection. This is the critical performance guard.

**Gate on `filters is not None`:** Even if a caller were to pass `reviewed=True` with
`filters=None` (bulk-sync mode), the code ignores `reviewed` and uses `find()`. This
makes the invariant explicit: the reviewed filter is a curation-only feature.

### Deviations from spec

None. The `_FIELD_ABOUT_ENTITY_MENTION` constant was reused as the `$lookup` join key
reference (`f"${_FIELD_ABOUT_ENTITY_MENTION}"`), which aligns with the spec's join
condition on the embedded triad.

### Files modified

- `src/ers/resolution_decision_store/adapters/decision_repository.py` — abstract
  signature + concrete implementation (`_fetch_with_review_filter`)
- `src/ers/curation/services/decision_curation_service.py` — `list_decisions` accepts
  and forwards `reviewed`
- `src/ers/curation/entrypoints/api/v1/decisions.py` — `reviewed: bool | None` query
  param, forwarded to service
- `test/unit/resolution_decision_store/adapters/test_decision_repository.py` — 5 new
  unit tests for pipeline shape
- `test/feature/link_curation_api/decision_browsing.feature` — 4 new Gherkin scenarios
- `test/feature/link_curation_api/test_decision_browsing.py` — 4 scenario bindings +
  step definitions
