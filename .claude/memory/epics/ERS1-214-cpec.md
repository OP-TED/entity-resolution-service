# ERS1-214 — Refresh-Bulk Cold Start & Idempotent ERE Outcomes

## Problem

Today, `POST /refresh-bulk` returns every Decision touched since `last_snapshot`. Two consequences are wrong for consumers:

1. **Cold start** — when a source has never called refresh-bulk, `last_snapshot` is `None`, and the first call returns **all** decisions for the source (including ones that have not actually moved). Consumers expect a "delta since you started asking" semantic, not a full backfill.
2. **ERE re-confirmation noise** — every ERE outcome currently bumps `updated_at`, even when ERE returns the same `current_placement.identifier` as already stored. Consumers see "updates" for placements that have not in fact changed.

The desired contract for refresh-bulk:

> **Return only decisions whose `current_placement` has changed since the consumer's last successful refresh-bulk call. Newly created decisions (mention seen for the first time) and ERE re-confirmations of an unchanged placement are NOT considered changes.**

## Scope

This ticket covers two coupled changes that together implement the desired contract:

1. **Write-path change:** `DecisionStoreService.store_decision` must short-circuit when the incoming `current_placement.identifier` matches the stored one. `updated_at` is bumped only when the placement actually changes. On first creation, `updated_at` stays unset (`None`).
2. **Read-path adjustment:** `query_decisions_delta` must, on cold start (`updated_since is None`), filter to decisions where `updated_at` is non-null. With the write-path change in place, this naturally returns only decisions whose placement has been corrected at least once.

No data migration is required — no production data exists yet.

## DocumentDB Cross-Engine Compatibility

The Decision Store changes target three Mongo-compatible engines: MongoDB, FerretDB (used in dev), and Amazon DocumentDB. DocumentDB has the strictest operator subset of the three. The ERS1-214 changes are written to work cleanly on all three:

### R2 stale filter

The stale filter is a flat two-branch `$or` with no nested `$and`/`$or` and no `$exists: false`:

```python
"$or": [
    {"updated_at": {"$lt": updated_at}},                              # already moved
    {"updated_at": None, "created_at": {"$lt": updated_at}},          # never moved
]
```

Relies on the MongoDB-family rule that `{field: None}` matches both null AND missing fields — supported identically on all three engines.

### R3 cold-start delta filter

The cold-start filter on `updated_at` is `{$exists: True}` only — no `$ne`:

```python
query[_FIELD_UPDATED_AT] = {"$exists": True}
```

This is sufficient because the insert path (R1) **omits** `updated_at` entirely; nothing in the codebase ever stores `{updated_at: null}` explicitly. The query then aligns exactly with the partial index `partialFilterExpression: {updated_at: {$exists: true}}`, so DocumentDB's planner reliably picks the index. Avoids `$ne` (DocumentDB does not use indexes well for `$ne`).

### Curation text search

`MongoEntityMentionCurationRepository.search_identifiers` was rewritten to use `$regex` over `$or` of two fields rather than MongoDB's `$text` operator:

```python
{"$or": [
    {"content": {"$regex": pattern, "$options": "i"}},
    {"parsed_representation": {"$regex": pattern, "$options": "i"}},
]}
```

DocumentDB does not support `$text` or text indexes at all. The legacy `resolution_requests_text` text index has been dropped from `MongoClientManager.ensure_indexes` (and the integration test fixture). Search returns documents whose `content` or `parsed_representation` contains the literal substring. The pattern is `re.escape`d to prevent metacharacter injection.

Trade-off: `$regex` has no linguistic stemming or scoring. For the curation UI use case (human-in-the-loop, small result sets) this is acceptable. If full-text relevance is needed in the future, DocumentDB would require Atlas Search (Mongo only) or an external service like OpenSearch.

### Cursor pagination — `$gt: None` over `$ne: None`

`commons/adapters/decision_repository.py::_build_cursor_condition` previously used `{sort_field: {$ne: None}}` in the branch that advances pagination past the null tier when ascending. The operator was correct but did not use indexes on DocumentDB.

It has been replaced with `{sort_field: {$gt: None}}`. In BSON sort order null is the smallest type, so `$gt: null` matches every document whose field is non-null and present — identical semantic to `$ne: null` but `$gt` is a range predicate that uses field indexes on MongoDB, FerretDB, and DocumentDB.

### Known minor items (left untouched)

- `users/adapters/user_repository.py::find_paginated` uses `{$regex: <input>, $options: "i"}` for case-insensitive email search. Works correctly on all engines but does not use indexes (the same on MongoDB and DocumentDB). Acceptable for the small admin/users collection. A proper performance fix would normalize emails to a lowercase indexed field — out of scope for ERS1-214.

## Out of Scope

- Curator-override write paths (do not exist yet; the rule below applies to them once introduced).
- API contract changes to `RefreshBulkResponse` / `RefreshBulkRequest`.
- Changes to `created_at` semantics (still set once on insert, never modified).
- Refresh-bulk snapshot-advance race condition (advancing to `now()` after the query rather than to the query-time bound) — tracked separately; do not bundle.
- Alternate "change-log collection" or `placement_changed_at` schema additions — explicitly rejected in favour of the simpler `updated_at == None` semantic.

## Requirements

### R1 — Write rule (Decision Store)

`DecisionStoreService.store_decision(identifier, current, candidates, updated_at)` MUST behave as follows:

| Pre-state | Incoming `current.identifier` | Behaviour | Stored `created_at` | Stored `updated_at` |
|---|---|---|---|---|
| No existing decision for triad | any | Insert | `updated_at` arg | **`None`** (not set) |
| Existing decision, same `current_placement.identifier` | matches stored | **No-op write.** Return the existing Decision. | unchanged | unchanged (still `None` if never moved) |
| Existing decision, different `current_placement.identifier` | differs from stored | Update `current_placement`, `candidates`, set `updated_at` to incoming arg | unchanged | incoming `updated_at` |

The `candidates` list is **not** part of the change-detection key. ERE returning the same top-1 placement with a reordered candidate list is treated as a no-op.

### R2 — Optimistic concurrency

Stale-outcome rejection (`StaleOutcomeError`) protects against out-of-order writes. The rule:

> **A write is fresh iff its timestamp is strictly greater than the latest known write timestamp on the stored record.**
> The latest known timestamp is `updated_at` if set, otherwise `created_at`.

Concrete cases:

- **Stored has `updated_at = T`** → incoming write with `updated_at <= T` is rejected as stale.
- **Stored has `updated_at` missing/null** (i.e. first insert, never moved) → incoming write with `updated_at <= created_at` is rejected as stale. This guards against out-of-order ERE deliveries where a newer outcome arrives first.
- **Stored has `updated_at` missing/null and incoming `updated_at > created_at`** → write succeeds (it is genuinely newer than the only known write).

The Mongo-level filter must encode this rule in a single atomic `find_one_and_update` to avoid races. Logically:

```text
fresh ⇔ (updated_at exists AND updated_at < incoming)
      ∨ (updated_at missing-or-null AND created_at < incoming)
```

### R3 — Read rule (refresh-bulk delta query)

`DecisionStoreService.query_decisions_delta` MUST be **routed to the existing `MongoDecisionRepository.find_delta_for_source` method** (currently dead code, lines 346–381). This isolates delta semantics from curation filters.

`MongoDecisionRepository.find_delta_for_source(source_id, updated_since, ...)` MUST behave as follows:

| `updated_since` arg | Mongo filter on `updated_at` |
|---|---|
| `None` (cold start) | `{"$ne": None, "$exists": True}` — return only decisions that have moved at least once |
| Any datetime `T` | `{"$gt": T}` — strictly after the snapshot (existing behaviour preserved) |

Source filter (`{_FIELD_SOURCE_ID: source_id}`) and cursor pagination are unchanged.

**`find_with_filters` and `_build_query` remain UNTOUCHED.** The cold-start semantic does NOT apply to curation filters — curation continues to filter only on what is provided in `DecisionFilters` and treats absent fields as "no constraint".

### R4 — Snapshot advance

`BulkRefreshCoordinatorService.refresh_bulk` continues to call `advance_snapshot(source_id, datetime.now(UTC))` when the final page is returned. Behaviour is unchanged at this layer; the cold-start fix lives in R3.

### R5 — Provisional singleton path

The `ResolutionCoordinatorService` provisional-write fallback (single-mention timeout) writes via `store_decision`. It MUST follow the same rule as R1:

- A provisional write for a never-seen-before mention inserts with `updated_at = None`.
- A provisional write that matches an already-stored placement (e.g., a prior ERE result with the same provisional ID — degenerate but possible) is a no-op.

No special-case logic needed at the coordinator layer; R1 handles it.

### R6 — `Decision` schema

The erspec `Decision` model already declares `updated_at: Optional[datetime]`. No schema change is needed. The ERS persistence layer must ensure that the field is genuinely allowed to be absent / null in MongoDB documents.

### R7 — Index

Update `MongoDecisionRepository.ensure_indexes` to add a refresh-bulk-specific partial index:

- **Existing** index `idx_decision_store_updated_at_id` on `(updated_at ASC, _id ASC)` — KEEP for the bulk-sync (`find_with_filters` with `filters=None`) path which sorts on `updated_at` only.
- **NEW** partial index `idx_decision_store_delta` on `(about_entity_mention.source_id ASC, updated_at ASC, _id ASC)` with `partialFilterExpression: {"updated_at": {"$exists": true}}`.
- Rationale: refresh-bulk's `find_delta_for_source` query is always `(source_id, updated_at > X | $ne null)`. A partial index excludes rows whose `updated_at` is unset (which can never match) and supports the source-scoped delta scan. **Note:** MongoDB rejects `$ne` in `partialFilterExpression` (only `$exists`, `$gt`, `$lt`, `$eq`, `$type`, `$and`, `$or` are allowed there). `$exists: true` is the equivalent expression because the insert path omits the `updated_at` field entirely (rather than setting it to `None`).
- Both indexes are created idempotently via `create_index` with `background=True`.

### R8 — Tracing / observability

- The "no-op write" branch in `store_decision` MUST emit a span attribute `decision_store.placement_unchanged = true` so it is distinguishable from genuine writes in traces.
- The cold-start branch in `query_decisions_delta` MUST emit `decision_store.cold_start = true`.
- No new log lines required beyond existing instrumentation.

## Acceptance Criteria

### AC1 — First-time insert creates with `updated_at = None`

- **Given** no Decision exists for triad `T`
- **When** `store_decision(T, cluster_A, [], 2026-05-05T10:00:00Z)` is called
- **Then** a Decision is inserted with `created_at = 2026-05-05T10:00:00Z`, `updated_at = None`, `current_placement = cluster_A`

### AC2 — ERE re-confirmation is a no-op

- **Given** a Decision exists for triad `T` with `current_placement = cluster_A`, `created_at = t1`, `updated_at = None`
- **When** `store_decision(T, cluster_A, [...], t2)` is called with `t2 > t1`
- **Then** the stored Decision is unchanged: `created_at = t1`, `updated_at = None`, `current_placement = cluster_A`
- **And** the returned value is the existing Decision

### AC3 — Genuine placement change bumps `updated_at`

- **Given** a Decision exists for triad `T` with `current_placement = cluster_A`, `updated_at = None`
- **When** `store_decision(T, cluster_B, [...], t2)` is called
- **Then** the stored Decision has `current_placement = cluster_B`, `updated_at = t2`, `created_at` unchanged

### AC4 — Cold-start refresh-bulk is empty for a never-changed source

- **Given** source `S` has 5 registered mentions, each with one Decision, all with `updated_at = None`
- **And** no `LookupRequestRecord` exists for `S` (`last_snapshot` unknown)
- **When** `POST /refresh-bulk` is called for `S`
- **Then** `deltas` is empty
- **And** `has_more` is `false`
- **And** `last_snapshot` is advanced to "now"

### AC5 — Cold-start refresh-bulk returns only changed decisions

- **Given** source `S` has 5 mentions; 2 of them have had a placement change (so their `updated_at` is non-null), 3 have not (`updated_at = None`)
- **And** no `LookupRequestRecord` exists for `S`
- **When** `POST /refresh-bulk` is called
- **Then** `deltas` contains exactly the 2 changed mentions
- **And** the 3 unchanged mentions are not in the response

### AC6 — Warm refresh-bulk preserves existing `$gt: T` semantic

- **Given** `last_snapshot = T` and 3 decisions with `updated_at` after `T`, 2 with `updated_at` before `T`, 4 with `updated_at = None`
- **When** `POST /refresh-bulk` is called
- **Then** exactly the 3 post-`T` decisions are returned

### AC7 — Stale-outcome check tolerates `None`

- **Given** a Decision exists with `updated_at = None`
- **When** `store_decision` is called with a different placement and any non-null `updated_at`
- **Then** the write succeeds (not rejected as stale)

### AC8 — Stale-outcome check rejects regressions

- **Given** a Decision exists with `updated_at = t2`
- **When** `store_decision` is called with a different placement and `updated_at = t1` where `t1 < t2`
- **Then** `StaleOutcomeError` is raised

### AC9 — Index filter is partial

- **Given** the Decision Store has been initialised
- **When** the indexes for the Decisions collection are inspected
- **Then** the `(source_id, updated_at)` index has `partialFilterExpression: {"updated_at": {"$exists": true}}`

## Test Coverage

### Unit (services/adapters)

| ID | Layer | Scenario |
|---|---|---|
| U-01 | `DecisionStoreService` | First insert: `updated_at` not set on stored doc |
| U-02 | `DecisionStoreService` | Same-placement re-write: returns existing, no Mongo update issued |
| U-03 | `DecisionStoreService` | Different-placement re-write: `updated_at` is bumped |
| U-04 | `DecisionStoreService` | Different-placement re-write: `created_at` is preserved |
| U-05 | `DecisionStoreService` | Stale write against `updated_at=None` is accepted |
| U-06 | `DecisionStoreService` | Stale write against later `updated_at` raises `StaleOutcomeError` |
| U-07 | `DecisionRepository` | `query_decisions_delta(updated_since=None)` filters on `$ne: null` |
| U-08 | `DecisionRepository` | `query_decisions_delta(updated_since=T)` filters on `$gt: T` |
| U-09 | `BulkRefreshCoordinatorService` | Cold-start path passes `updated_since=None` and advances snapshot |

### Integration (real Mongo)

| ID | Scenario |
|---|---|
| I-01 | Insert → re-insert same placement → `updated_at` still null in DB |
| I-02 | Insert → re-insert different placement → `updated_at` set, `created_at` unchanged |
| I-03 | Cold-start refresh-bulk against pre-seeded data: returns only docs where `updated_at != null` |
| I-04 | Partial index exists with correct filter |
| I-05 | Concurrent same-placement writes do not produce phantom updates |

### Feature / BDD

| ID | Scenario |
|---|---|
| F-01 | `Given a fresh ERS deployment, When a source's first refresh-bulk is called and ERE has only ever returned the same placement for each mention, Then the response is empty` |
| F-02 | `Given a source with one corrected placement among many stable resolutions, When refresh-bulk is called for the first time, Then only the corrected placement is returned` |
| F-03 | `Given an ongoing refresh-bulk consumer, When ERE re-confirms the same placement for a previously-changed mention, Then the next refresh-bulk does NOT include that mention again` |

## Risks & Open Questions

- **Open question — what counts as "the same placement"?** This spec uses `current_placement.identifier` only. Confidence/similarity score changes do not count. Confirm with product that this is the intended semantic.
- **Open question — should `candidates` differences trigger updates?** This spec says no. If consumers display candidates, this is wrong. Confirm with product.
- **Risk — race window on `advance_snapshot`.** Tracked separately. The fix in this ticket does not introduce or worsen the race; it leaves the existing `advance_snapshot(now())` behaviour intact. The race ticket should follow.
- **Risk — performance of read-before-write in `store_decision`.** Adds one Mongo read per ERE outcome. Acceptable given current throughput; revisit if outcome rate grows. Alternative (single-round-trip aggregation-pipeline conditional update) is documented but not selected for clarity.

## Dependencies & Touched Files

**Production code:**

- `src/ers/resolution_decision_store/services/decision_store_service.py`
  - `DecisionStoreService.store_decision` — add same-placement short-circuit before write (R1)
  - `DecisionStoreService.query_decisions_delta` — call `repository.find_delta_for_source` instead of `find_with_filters` (R3 routing)
- `src/ers/resolution_decision_store/adapters/decision_repository.py`
  - `MongoDecisionRepository.upsert_decision` — split insert (no `updated_at`) vs update (set `updated_at`) flows; relax `_execute_upsert` stale filter to tolerate `None` (R1, R2)
  - `MongoDecisionRepository.find_delta_for_source` — apply cold-start `$ne: null` filter (R3)
  - `MongoDecisionRepository.ensure_indexes` — add `idx_decision_store_delta` partial index (R7)
  - `_build_query` and `find_with_filters` — UNTOUCHED (curation isolation)

**Tests requiring update (semantic change):**

- `test/unit/resolution_decision_store/services/test_decision_store_delta.py` — repoint mocks from `find_with_filters` to `find_delta_for_source`; add cold-start `$ne: null` assertion (5 affected tests)
- `test/unit/resolution_decision_store/services/test_decision_store_service.py` — add tests for same-placement short-circuit (R1); existing `test_delegates_to_repository` adjusts to verify pre-read happens
- `test/unit/resolution_decision_store/adapters/test_decision_repository.py` — split into insert-path and update-path tests; new None-tolerant stale tests; partial-index assertion
- `test/unit/resolution_coordinator/services/test_bulk_refresh_coordinator_service.py::test_returns_all_on_first_lookup` — **semantic inversion**: cold-start with no real changes returns empty
- `test/integration/resolution_decision_store/test_decision_repository.py` — new IT for insert sets `updated_at=None`; existing IT-001/IT-003 may need adjustment
- `test/integration/resolution_coordinator/test_resolution_coordinator_integration.py::test_it007_bulk_refresh_delta`, `test_it008_bulk_refresh_first_lookup` — semantic change
- `test/feature/resolution_decision_store/test_store_decision.py` (3 BDD steps) — adjust to new semantic
- `test/feature/resolution_coordinator/test_bulk_lookup.py` — verify cold-start scenario
- `test/integration/ere_result_integrator/test_outcome_integration.py::test_it002_unsolicited_outcome_updates_decision_store` — verify same-placement re-write does NOT bump `updated_at`

**Docs (must update for spec coherence):**

- `.claude/memory/epics/ers-epic-06-resolution-coordinator/EPIC.md` (IT-008 line 315) — change acceptance from "all decisions for source returned" to "only decisions whose placement has changed since first persisted"
- `.claude/memory/epics/ers-epic-06-resolution-coordinator/task65-bulk-refresh-coordinator-service.md` lines 82, 193 — update inline comment and `test_returns_all_on_first_lookup` row

## Rollout Plan

1. Land write-path change (R1, R2) with unit tests U-01..U-06.
2. Land read-path change (R3) with unit tests U-07..U-08.
3. Update partial index (R7) — index migration script if needed.
4. Update bulk-refresh tests (U-09, BDD F-01..F-03) to reflect new semantic.
5. Update spec documents (`EPIC.md` IT-008 acceptance, `task65-...md` table).
6. Single PR — no production data, no staged rollout needed.
