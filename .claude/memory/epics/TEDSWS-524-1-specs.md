# TEDSWS-524-1 — Follow-up specifications

Follow-ups arising from the TEDSWS-524 / TEDSWS-522 implementation and its code
review, plus two newly surfaced concerns:

- **B** — what ERE-outcome integration does to the stores (decision / cluster-size / user-action).
- **C** — TEDSWS-530: curator reject / assign actions must actually reach ERE.

> Filename note: created as `TEDSWS-524-1-specs.md` (the requested `sepcs` was a typo).

Priority order: **C (client-reported bug, and it gates the review-state loop) → B → A.**

---

## A. Code-review follow-ups (from TEDSWS-524)

These are recorded in `TEDSWS-524-delta-plan.md`; restated here as scoped work items.

### A1 — Cross-module data coupling (design smell)
`previous_review_count` lives on the `decisions` document (owned by
`resolution_decision_store`) but is written by `curation`'s `user_action_service`;
`find_reviewed_since_placement` reads the `user_actions` collection (owned by
`curation`) from inside the decision-store adapter. Contract-legal (import-linter
passes) but each module encodes the other's storage schema.

- **Target:** introduce a read-port abstraction for review-state, or move the
  review-state reads to a curation-side adapter; keep a single owner per collection.
- **Files:** `resolution_decision_store/adapters/decision_repository.py`
  (`find_reviewed_since_placement`, `increment_review_count`, `find_review_counts`),
  `curation/services/{user_action_service,decision_curation_service}.py`.
- **Acceptance:** no module hard-codes a sibling module's collection name/schema;
  dependency flows through an interface.

### A2 — Real-DB (FerretDB/DocumentDB) integration coverage
The new `previous_review_count {"$in": [0, None]}` match and the `$or`-of-subdocuments
in `find_reviewed_since_placement` are exercised only against mocks.

- **Target:** integration tests against the FerretDB testcontainer covering:
  `ever_reviewed=true|false` partitioning (incl. missing-counter docs);
  `find_reviewed_since_placement` with an action straddling the placement boundary;
  combined `ever_reviewed` + `reviewed_since_placement`.
- **Files:** `test/integration/resolution_decision_store/test_decision_repository.py`.
- **Acceptance:** the engine-specific operators are proven on the production engine.

### A3 — `CursorPage.count` ignores the `reviewed_since_placement` filter
`count_documents(query)` runs before the user_actions `$lookup`, so totals over-report
when that filter is active (pre-existing for the old `reviewed` flag).

- **Target:** either compute count within the same aggregation (`$count` facet) when
  the review filter is active, or document that `count` is unfiltered for that filter.
- **Acceptance:** UI total matches the filtered result set, or the contract is explicit.

### A4 — Concurrent page reads / port consolidation
`list_decisions` issues `find_by_identifiers`, `find_review_counts`,
`find_reviewed_since_placement` sequentially with no data dependency.

- **Target:** run independent reads via `asyncio.gather`; consider merging the two
  review-state reads into one port method (ISP — one "attach review state" call).
- **Files:** `curation/services/decision_curation_service.py:list_decisions`.

### A5 — `$gt` vs `$gte` boundary alignment
`find_reviewed_since_placement` / the lookup use `$gt` on the placement boundary;
`user_action_repository.has_current_action` uses `$gte`. Harmless today (an action
cannot equal the placement instant), but inconsistent.

- **Target:** pick one (recommend `$gt`) and align both call sites; add a boundary test
  (action `created_at == since` must be treated consistently).

---

## B. ERE-outcome integration — impact on the stores

When ERE delivers a clustering outcome, `outcome_integration_service.integrate_outcome`
→ `DecisionStoreService.store_decision` applies it. This section specifies the intended
effect on each store and the invariants/edge cases to guarantee.

### B1 — Per-store effect (intended contract)

| Store / field | Effect on ERE integration | Owner / mechanism |
|---|---|---|
| **Decision projection** (`decisions`) | Overwritten with the new outcome **iff the outcome is material** (placement or candidates changed — TEDSWS-524 §6.1). `updated_at` advances; identical replay is a no-op. | `store_decision` + `is_same_outcome` |
| **`cluster_sizes`** | `shift(from=old_cluster, to=new_cluster)` on placement change; `shift(None → new)` on first insert; `shift(X → X)` no-op when cluster unchanged (even if confidence changed). | `ClusterSizeIndex.shift` |
| **`user_actions`** | **Untouched.** The curator action log is the stable trace; ERE integration never reads or writes it. | — |
| **`previous_review_count`** (on the decision doc) | **Preserved** — the integrator writes only its own fields; the counter carries across re-integrations. | `decision_repository` `$set` excludes the counter |
| **`reviewed_since_placement`** (derived) | Flips to `false` automatically when `updated_at` advances past the last action — no write needed. | derived on read |

### B2 — Invariants to hold
1. **Idempotent replay:** an identical ERE outcome causes **zero** writes to any store
   (no decision write, no `cluster_sizes` shift, no counter change).
2. **Single writer per derived value:** only the integrator shifts `cluster_sizes`;
   only `user_action_service` increments `previous_review_count`.
3. **Counter durability:** re-integration must never reset `previous_review_count`.
4. **Cluster-size conservation:** `sum(cluster_sizes.size)` equals the number of
   decisions whose `current_placement.cluster_id` is set (modulo in-flight writes).

### B3 — Edge cases / gaps to resolve (each needs a test)
- **Cluster emptied to size 0:** when the last decision leaves a cluster, the
  `cluster_sizes` entry lingers at `size: 0`. Decide: delete-on-zero vs keep-zero.
  Impacts stats (`cluster_singletons_count`, median, p95 must ignore `size: 0`).
- **Decrement-below-zero guard:** `shift` must never produce a negative size (assert /
  clamp); a missing `from` entry on decrement must not corrupt the projection.
- **First-integration ordering:** the `cluster_sizes` increment and the decision insert
  are two writes; specify behaviour if one fails (reconcilable via the backfill /
  invariant-verification script).
- **Decision deletion / source purge:** if a delete path exists (or is added), it must
  `shift(from=cluster, to=None)` and leave `user_actions` intact. If no delete path
  exists, state that explicitly.
- **Immutable triad:** entity_type/source_id/request_id never change on re-integration,
  so the decision `_id` (triad hash) and all `user_actions` joins remain stable —
  confirm and test.
- **Bulk refresh:** `bulkWrite` of deltas must compute net `cluster_sizes` shifts
  correctly when many decisions move in one batch.

### B4 — Acceptance
A re-integration suite proves: material change → decision rewritten + `updated_at`
bumped + `cluster_sizes` shifted + counter preserved + `reviewed_since_placement`
flips to false; identical replay → all stores unchanged; cluster emptied → stats
unaffected by the zero/removed entry.

---

## C. TEDSWS-530 — curator actions must reach ERE (reject-all / select-alternative)

### C1 — Requirement (was missing from the original spec)
When a curator **rejects all recommendations** or **selects an alternative cluster**,
ERS must inform ERE so it can re-resolve. This is an additional ERE call over the same
Redis request channel, carrying optional parameters:
- **reject all** → `excluded_cluster_ids` (the clusters the curator ruled out).
- **select alternative** → `proposed_cluster_ids` (the cluster the curator chose).
- **accept top** → `proposed_cluster_ids = [current placement]` (re-confirm).

The returning ERE outcome flows back through B (integration) and, if material,
advances `updated_at` → the decision re-surfaces as "needs revisit". **C therefore
gates the entire TEDSWS-524 review-state loop**: if these calls never reach ERE, the
four-state model never receives the updates it is designed to surface.

### C2 — Client symptom (TEDSWS-530)
> "When a user rejects a decision in the curation app, the log does not show this
> reflected in the corresponding JSON payload (`excluded_cluster_ids`)."

### C3 — What the code already does (so this is a *bug*, not greenfield)
`decision_curation_service` already wires all three actions to ERE via
`_publish_reevaluation`:
- `accept_decision` → `proposed_cluster_ids=[current_placement.cluster_id]`
- `reject_decision` → `excluded_cluster_ids=[c.cluster_id for c in decision.candidates]`
- `assign_decision` → `proposed_cluster_ids=[cluster_id]`

Verified **not** the cause:
- The request model `erspec.models.ere.EntityMentionResolutionRequest` **does** define
  `proposed_cluster_ids` and `excluded_cluster_ids` (defaults `[]`).
- `EREPublishService.publish_request` → `push_request` serializes with full
  `model_dump_json()` (no `exclude_none` / `exclude_defaults`), so a populated list
  **is** included in the payload.

### C4 — Root-cause candidates (to confirm via logs/repro), ranked
1. **Silent swallow (most likely contributor).** `_publish_reevaluation` wraps the
   publish in `except Exception: log.exception(...)` and returns. Any failure
   (channel unavailable, zero-accepted, serialization, connection) is logged as an
   error but the curation action still returns success — so to the curator/app the
   reject "succeeded" while ERE received nothing. Fire-and-forget with no retry/outbox.
2. **Empty `excluded_cluster_ids`.** If `decision.candidates` is empty at reject time
   (ERE returned no alternatives, or candidates were truncated to 0), the payload
   carries `"excluded_cluster_ids": []` — i.e. nothing actionable, matching "not
   reflected". Needs confirmation that the loaded `Decision` populates `candidates`.
3. **Semantic gap — current placement not excluded (CONFIRMED, must fix).** "Reject
   all recommendations" excludes only `candidates`; it does **not** exclude
   `current_placement.cluster_id`. Per product decision, a full reject must rule out
   the current placement **and** all candidates. The exclusion set is therefore
   incomplete today.
4. **Action recorded but publish skipped.** If `record_reject` raises
   `AlreadyCuratedError` (idempotency guard) the publish is never reached — but that
   surfaces as HTTP 409, so it is distinguishable in logs.

### C5 — Required behaviour / fixes (product decisions baked in)
- **Correct exclusion set on reject (primary fix).** "Reject all" must exclude
  `current_placement.cluster_id` **and** every `candidates[*].cluster_id`, deduplicated.
  Confirm `candidates` is actually loaded on the `/reject` path so the set is non-empty.
- **Audit the outgoing call (so the client can verify in logs).** Log the **outgoing
  payload summary** at INFO — action type, `proposed_cluster_ids`, `excluded_cluster_ids`,
  `ere_request_id` — on every successful publish. This directly answers the TEDSWS-530
  diagnostic (logs currently don't show the exclusions).
- **Delivery stays best-effort (product decision).** Keep the current fire-and-forget:
  no outbox, no retry, and a publish failure is **swallowed silently** (logged at
  WARNING/ERROR, not raised) — the curation action still succeeds and the UI is **not**
  blocked or flagged. Not critical at the moment; revisit if delivery reliability
  becomes an issue.
- **Confirm wiring end-to-end** from the `/reject` and `/assign` routes through to a
  message actually accepted by the Redis channel.

### C6 — Files
- `src/ers/curation/services/decision_curation_service.py`
  (`_publish_reevaluation`, `reject_decision`, `assign_decision`, `accept_decision`).
- `src/ers/ere_contract_client/services/ere_publish_service.py` (observability of the
  published payload; failure surfacing).
- (If outbox/retry adopted) a small durable-retry component — flagged as a decision.

### C7 — Tests / acceptance
- **Unit:** `reject_decision` publishes a request whose `excluded_cluster_ids` equals
  `{current_placement.cluster_id} ∪ {candidates[*].cluster_id}`, deduplicated and
  non-empty; `assign_decision` publishes `proposed_cluster_ids=[chosen]`;
  `accept_decision` re-confirms the current placement.
- **Unit:** a publish failure is **swallowed** — the curation action still returns
  success (no exception propagates) and is logged, confirming the best-effort contract.
- **Unit:** the success path logs the outgoing payload summary including the
  `excluded_cluster_ids` (the TEDSWS-530 auditability fix).
- **Feature (BDD):** "Rejecting all recommendations sends ERE an exclusion request" —
  POST `/reject`, assert the message handed to the Redis channel carries
  `excluded_cluster_ids` containing the current placement and the candidates.
  Mirror for `/assign`.
- **Acceptance:** the reject payload visible in the logs/channel contains the excluded
  cluster IDs (current placement + candidates); a publish failure does not break the
  curation action or block the UI; the re-eval round-trip advances `updated_at` and
  flips the decision to "needs revisit".

### C8 — Resolved product decisions
- **Reject-all exclusion set:** exclude the **current placement AND** the candidate
  list (deduplicated).
- **Delivery policy:** **best-effort** — no outbox/retry.
- **Publish failure:** **silently swallowed** (logged, not raised); the curator action
  is not blocked or flagged in the UI. Acceptable for now; revisit if needed.

---

## Suggested delivery order
1. **C** (TEDSWS-530) — diagnose root cause from logs/repro, add observability, fix the
   exclusion set + failure surfacing, lock with tests. Unblocks the review-state loop.
2. **B** — re-integration store-impact invariants + edge-case tests (cluster-size zero
   handling, decrement guard).
3. **A** — review-driven hardening (coupling refactor, FerretDB integration tests,
   count semantics, concurrency, boundary alignment).

