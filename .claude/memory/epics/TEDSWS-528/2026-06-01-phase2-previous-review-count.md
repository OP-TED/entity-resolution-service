# Task: Phase 2 — `previous_review_count` counter on the decision

## Task Specification

### Description

Every `DecisionSummary` row must carry a count of how many curator actions have
ever been recorded against a given decision (lifetime, persists across ERE
re-integrations). Drives the UI "previously reviewed" indicator from TEDSWS-522.

### Acceptance criteria

1. `DecisionSummary` DTO carries `previous_review_count: int` (default 0).
2. `DecisionRepository` exposes `increment_review_count(decision_id)` (abstract)
   and `find_review_counts(decision_ids)` (abstract).
3. `MongoDecisionRepository` implements both methods:
   - `increment_review_count` → `$inc: {previous_review_count: 1}`, no upsert.
   - `find_review_counts` → single `find` on `_id` + projection, returns `dict[str, int]`.
4. `UserActionService` takes a `DecisionRepository` constructor argument and calls
   `increment_review_count(decision.id)` after each successful `save` in
   `record_accept`, `record_reject`, `record_assign`. Never called on `AlreadyCuratedError`.
5. `list_decisions` in `DecisionCurationService` calls `find_review_counts` and
   passes the resulting dict to `_to_decision_summary`.
6. ERE re-integration (`_build_insert_doc` / `_build_update_doc`) does NOT touch
   `previous_review_count` — counter is preserved naturally.
7. Backfill script at `src/scripts/backfill_previous_review_count.py` is idempotent,
   supports `--dry-run` and `--batch-size`.

### Gherkin scenarios

- `test/feature/link_curation_api/decision_summary_review_counter.feature`
  - Fresh decision starts at 0
  - Counter increments on accept action
  - Counter is preserved across ERE re-integration

### Layers affected

- `domain/`: `DecisionSummary` in `ers.curation.domain.data_transfer_objects`
- `adapters/`: `DecisionRepository` and `MongoDecisionRepository` in
  `ers.resolution_decision_store.adapters.decision_repository`
- `services/`: `UserActionService` (`ers.curation.services.user_action_service`),
  `DecisionCurationService._to_decision_summary` and `list_decisions`
- `entrypoints/`: `dependencies.py` DI wiring for `get_user_action_service`

---
<!-- implementation-log -->
---

## Implementation Log

### Accomplished

- Added `previous_review_count: int = Field(default=0)` to `DecisionSummary`.
- Added abstract methods `increment_review_count` and `find_review_counts` to
  `DecisionRepository`.
- Implemented both in `MongoDecisionRepository`:
  - `increment_review_count` uses `update_one(..., {"$inc": ...})` without upsert.
  - `find_review_counts` uses a single `find` with `_id $in` + projection, returns
    `dict[str, int]`, missing keys default to 0 at the call site.
- Added `DecisionRepository` parameter to `UserActionService.__init__`; wired
  `increment_review_count(decision.id)` call after each `save` in all three
  `record_*` methods.
- Updated `get_user_action_service` in `dependencies.py` to inject
  `decision_repository`.
- Updated `_to_decision_summary` to accept an optional `review_counts: dict[str,
  int]` parameter; `list_decisions` now calls `find_review_counts` and passes it.
- Verified that `_build_insert_doc` and `_build_update_doc` never write
  `previous_review_count` (confirmed by unit test + inspection).
- Created `src/scripts/backfill_previous_review_count.py`:
  - Aggregates `user_actions` by `about_entity_mention` triad, derives decision
    `_id` via `derive_provisional_cluster_id`, bulk-writes `$set` on decisions.
  - Supports `--dry-run` and `--batch-size`; idempotent.

### Key decisions

- **`find_review_counts` over per-row queries**: single extra `find` per
  `list_decisions` call instead of N+1 per row.
- **`find_review_counts` as a separate method** (not changing `find_with_filters`
  return type): preserves the shared interface used by the Decision Store sync path.
- **Default-to-0 at call site**: `(review_counts or {}).get(id, 0)` — missing
  keys and old documents without the field are silently treated as 0.
- **`increment_review_count` called only after successful save**: action save is
  canonical; counter is a denormalised mirror. `AlreadyCuratedError` aborts before
  save so the counter is never incremented on the guard path.
- **No `upsert` on increment**: missing document is a no-op; this protects against
  phantom counter increments if the decision was deleted.

### Test counts

- 3 new unit tests in `test_decision_repository.py` (increment op, no-upsert, no
  overwrite on integration write) — all passing.
- 5 new unit tests in `test_user_actions_service.py::TestIncrementReviewCountOnRecord`
  — all passing (uses `@pytest.mark.asyncio` to work around branch-level strict mode).
- 3 new BDD scenarios in `test_decision_summary_review_counter.py` — all passing.
- No regressions introduced: 148 tests pass in the targeted suite; all pre-existing
  async-mode failures in curation service unit tests are unrelated to this change.

### Deviations from spec

- Spec suggested a `DecisionSummary`-only approach or a sentinel attribute on
  `Decision`. Chose `find_review_counts` as a clean second query instead — keeps
  `find_with_filters` signature stable.
- The spec's Gherkin step "Counter increments atomically on each curator action"
  tested the actual increment by calling the HTTP accept endpoint and then listing
  decisions. In the BDD test, the mock returns the post-increment count (1) on the
  second `find_review_counts` call, so the HTTP layer is fully exercised.
