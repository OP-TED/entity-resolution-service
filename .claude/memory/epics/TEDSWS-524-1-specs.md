# TEDSWS-524-1 — Follow-up specifications

Follow-ups arising from the TEDSWS-524 / TEDSWS-522 implementation and its code
review, plus two newly surfaced concerns:

- **B** — what ERE-outcome integration does to the stores (decision / cluster-size / user-action).
- **C** — TEDSWS-530: curator reject / assign actions must actually reach ERE.

> Filename note: created as `TEDSWS-524-1-specs.md` (the requested `sepcs` was a typo).

Priority order: **C (client-reported bug, and it gates the review-state loop) → B → A.**

### Normative basis (ers-docs)

Cross-checked against the `entity-resolution-docs` repo. The governing artefacts:

| This spec | Normative home in ers-docs |
|---|---|
| **B** — ERE-outcome integration → stores | Spine B (`spine-b.adoc`); UC-B1.2 *Integrate ERE Outcomes*; ADR-B2N *Decision Projection & User Action Log*; ADR-D1N *Authoritative Stores & State Separation*; ADR-A3N *Identifier Stability* |
| **C** — curator actions → ERE re-evaluation | Spine D (`spine-d.adoc`); UC-W2 / UC-B2.1 *Recommend Resolution Update*; ADR-E1N *Recluster & Re-resolution Requests*; ADR-C2N *Message Types & Delivery Semantics* |
| **Field/message contract** | `ERS-ERE-Contract/interface.adoc` — the **single normative source** for field names and message shapes |
| **Review-state model (TEDSWS-524)** | ADR-B2N *No Governance Lifecycle in ERS* — the two-primitive model (counter + derived flag) is compliant because it stores **no** `proposed/accepted/rejected/confirmed` status |

**Vocabulary note.** ADR-C2N and ADR-E1N still use an older action vocabulary
(`recommended_placement` / `recommended_exclusions`,
`resolveConsideringRecommendation` / `reResolveConsideringExclusions`) and both
carry an explicit `// TODO: reconcile against ERS–ERE contract`. The spines and the
contract use `proposed_cluster_ids` / `excluded_cluster_ids`. This spec and the code
track the **contract** (`interface.adoc`), which is the normative tie-breaker.

---

## A. Code-review follow-ups (from TEDSWS-524)

These are recorded in `TEDSWS-524-delta-plan.md`; restated here as scoped work items.

### A1 — Cross-module data coupling (design smell)
`previous_review_count` lives on the `decisions` document (owned by
`resolution_decision_store`) but is written by `curation`'s `user_action_service`;
`find_reviewed_since_placement` reads the `user_actions` collection (owned by
`curation`) from inside the decision-store adapter. Contract-legal (import-linter
passes) but each module encodes the other's storage schema.

This is not just an import-graph nicety: ADR-D1N and ADR-B2N deliberately **separate**
the Decision Projection store from the User Action Log. `previous_review_count` is
review/curation metadata, so placing it on the decision-projection document blurs that
documented boundary — which is the architectural argument for moving it (or its read
port) to the curation side.

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

An incoming outcome is applied only if it passes **both** guards from B2 — newer
(`updated_at`) **and** materially different. The table below assumes an applied outcome.

| Store / field | Effect on ERE integration | Owner / mechanism |
|---|---|---|
| **Decision projection** (`decisions`) | Overwritten when the outcome is newer **and** material (placement or candidates changed — TEDSWS-524 §6.1). `updated_at` advances. Stale outcome ⇒ rejected; identical replay ⇒ no-op. | `store_decision` (stale guard + `is_same_outcome`) |
| **`cluster_sizes`** | `shift(from=old_cluster, to=new_cluster)` on placement change; `shift(None → new)` on first insert; `shift(X → X)` no-op when cluster unchanged (even if confidence changed). | `ClusterSizeIndex.shift` |
| **`user_actions`** | **Untouched.** The curator action log is the stable trace; ERE integration never reads or writes it. | — |
| **`previous_review_count`** (on the decision doc) | **Preserved** — the integrator writes only its own fields; the counter carries across re-integrations. | `decision_repository` `$set` excludes the counter |
| **`reviewed_since_placement`** (derived) | Flips to `false` automatically when `updated_at` advances past the last action — no write needed. | derived on read |

> **Store-taxonomy note.** ADR-D1N names exactly three ERS stores: System of Record,
> Decision Projection, and User Action Log. `cluster_sizes` is **not** one of them — it
> is an internal derived projection (counts only), which ADR-D1N permits as an
> implementation-level optimisation. It holds no authoritative identity state, so it can
> evolve freely as long as the Decision Projection stays the source for placement.

### B2 — Two distinct write guards (do not conflate them)

The integration path has **two** independent guards. They protect against different
things and both already exist in the code:

1. **Stale-outcome guard (ordering).** `upsert_decision` rejects any outcome whose
   `updated_at` is **not newer** than the stored one (stored `updated_at >= incoming`
   ⇒ `StaleOutcomeError`, caught and ignored by the integrator). This implements
   Spine B's normative rule — *"accept an outcome only if it is not stale… using a
   monotonic outcome marker"* — keyed on the ERE response `timestamp`. It handles
   **late and out-of-order** deliveries (at-least-once).
2. **Material-change short-circuit (idempotency).** *After* the stale guard, if the
   incoming outcome is newer **but structurally identical** to the stored one
   (`is_same_outcome`: same placement **and** same truncated candidates), the write is
   skipped. This handles **duplicate** deliveries of the same outcome.

> `is_same_outcome` is **not** the ordering control — it only suppresses identical
> replays. Ordering is the stale guard's job. A late, older, *structurally different*
> outcome is rejected by guard 1, never reaching guard 2.

### B3 — Invariants to hold
1. **Ordering / latest-wins:** for a triad, the stored decision always reflects the
   outcome with the most recent `updated_at`; stale outcomes never overwrite it
   (Spine B; ADR-C2N idempotent-but-unordered).
2. **Idempotent replay:** an identical, non-stale ERE outcome causes **zero** writes to
   any store (no decision write, no `cluster_sizes` shift, no counter change).
3. **Single writer per derived value:** only the integrator shifts `cluster_sizes`;
   only `user_action_service` increments `previous_review_count`.
4. **Counter durability:** re-integration must never reset `previous_review_count`.
5. **Cluster-size conservation:** `sum(cluster_sizes.size)` equals the number of
   decisions whose `current_placement.cluster_id` is set (modulo in-flight writes).

### B4 — Edge cases / gaps to resolve (each needs a test)
- **Cluster emptied to size 0:** when the last decision leaves a cluster, the
  `cluster_sizes` entry lingers at `size: 0`. Decide: delete-on-zero vs keep-zero.
  Impacts stats (`cluster_singletons_count`, median, p95 must ignore `size: 0`).
  ADR-A3N (identifier non-revocation — *"a `cluster_id` remains reserved even if the
  cluster becomes empty"*) governs the **authoritative** id, which lives in ERE, not in
  `cluster_sizes`. So either choice is contract-safe for this **count** projection;
  pick delete-on-zero unless stats need the zero row.
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

### B5 — Acceptance
A re-integration suite proves:
- **material change** → decision rewritten + `updated_at` bumped + `cluster_sizes`
  shifted + counter preserved + `reviewed_since_placement` flips to false;
- **identical replay** (newer or equal, same outcome) → all stores unchanged;
- **stale / out-of-order outcome** (older `updated_at`) → rejected, all stores
  unchanged, even if the placement differs;
- **cluster emptied** → stats unaffected by the zero/removed entry.

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
`_publish_reevaluation`. Mapped to Spine D's curator vocabulary
(`acceptTop` / `acceptAlt` / `rejectAll`) and the contract fields:

| Action | Spine D | Published field |
|---|---|---|
| `accept_decision` | `acceptTop` | `proposed_cluster_ids=[current_placement.cluster_id]` |
| `assign_decision` | `acceptAlt` | `proposed_cluster_ids=[chosen_cluster_id]` |
| `reject_decision` | `rejectAll` | `excluded_cluster_ids=[c.cluster_id for c in decision.candidates]` |

This wiring matches Spine D and ADR-E1N (recommendation-only, ERE-authoritative), so the
defect is in the **exclusion set**, not in whether a call is made.

Verified **not** the cause:
- The request model `erspec.models.ere.EntityMentionResolutionRequest` **does** define
  `proposed_cluster_ids` and `excluded_cluster_ids` (defaults `[]`).
- `EREPublishService.publish_request` → `push_request` serializes with full
  `model_dump_json()` (no `exclude_none` / `exclude_defaults`), so a populated list
  **is** included in the payload.

Verified **as** the cause (see C4#3): at integration time
(`outcome_integration_service`) the stored decision is split
`current = response.candidates[0]` / `candidates = response.candidates[1:]`. So
`Decision.candidates` holds the **alternatives only — never the current placement.**
Excluding only `decision.candidates` on reject therefore leaks the placement to ERE as
still valid.

### C4 — Root-cause analysis (one confirmed; the rest to confirm via logs/repro)
> Item 3 is **confirmed** (see C3). Items 1, 2, 4 are additional contributors to
> verify from logs — they are not mutually exclusive.

1. **Silent swallow (most likely additional contributor).** `_publish_reevaluation`
   wraps the publish in `except Exception: log.exception(...)` and returns. Any failure
   (channel unavailable, serialization error, connection drop) is logged as an error but
   the curation action still returns success — so to the curator/app the reject
   "succeeded" while ERE received nothing. Fire-and-forget with no retry/outbox.
2. **Empty `excluded_cluster_ids`.** If `decision.candidates` is empty at reject time
   (ERE returned no alternatives, or candidates were truncated to 0), the payload
   carries `"excluded_cluster_ids": []` — i.e. nothing actionable, matching "not
   reflected". Needs confirmation that the loaded `Decision` populates `candidates`.
3. **Semantic gap — current placement not excluded (CONFIRMED, must fix).** Confirmed
   by the `candidates[0]` / `candidates[1:]` split in C3: `decision.candidates` never
   contains the current placement, so "reject all" excludes the alternatives but leaves
   `current_placement.cluster_id` un-excluded. Per product decision, a full reject must
   rule out the current placement **and** all candidates. This is the primary fix.
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
  - *Doc reconciliation (accepted deviation).* This is weaker than ADR-C2N's
    at-least-once intent and than Spine D's `202 Accepted`, which means *"recorded **and**
    forwarded"*. A dropped publish here is effectively at-most-once and the curator still
    sees success. We accept this consciously. It does **not** violate UC-B1.2 (*"if ERS
    cannot publish… the failure is logged and no Decision Store state is modified"*),
    and the lingering User Action Log entry is consistent with ADR-B2N (the log records
    what was **submitted**, not what was delivered). If reliability is later required, a
    retry/outbox closes the gap without changing the contract.
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


---

## Update — 2026-06-05 — TEDSWS-524-2 milestone 1 landed

The `feature/TEDSWS-524-2-review-state` branch materialises `reviewed_since_placement`
as a stored field on the decision row (joining the existing `previous_review_count`
counter). The following follow-up items from this spec are **resolved** by that
work; the rest remain or are re-scoped:

| Item | Status after TEDSWS-524-2 milestone 1 |
|---|---|
| A1 (cross-module data coupling) | **Resolved on the read side only.** The read predicate moved from `ReviewStateReader` into the writer (`record_review`); both materialised primitives are now read from the decision row. The decision-row placement of curation-derived data is accepted as the project's working convention. A future milestone could move both to a curation-owned collection. |
| A2 (real-DB integration coverage) | **Resolved.** New `test_review_state_lifecycle.py` and `test_decision_repository_pagination_across_pages.py` cover the new writers/filters end-to-end on FerretDB. |
| A3 (`CursorPage.count` under-counts with review filter) | **Resolved.** The review predicate is a stored-field `$match` and runs through `count_documents` like every other filter. The paginated-across-pages tests assert exact counts. |
| A4 (concurrent fan-out reads) | **Improved.** `find_review_counts` + `ReviewStateReader.reviewed_since_placement` are folded into a single `find_review_metadata`; `list_decisions` now issues two concurrent reads instead of three. |
| A5 (`$gt` vs `$gte` boundary alignment) | **Confirmed.** Both writers compare with strict `$gt`; `has_current_action` already uses `$gt`. |
| B (re-integration store impact) | **Tested.** New lifecycle tests cover `material change resets flag preserves counter`, `stale outcome rejected leaves materialised state untouched`, `cluster_sizes shift behavior is unchanged`. |
| C (TEDSWS-530 reach-ERE on reject) | Unchanged — already shipped on TEDSWS-524-1. |

**Cluster-size pagination bug (C1)** is **not** addressed by this milestone — it is
the entire scope of milestone 2 (`feature/TEDSWS-524-2-cluster-size-cursor-fix` to
come).

---

## Update — 2026-06-07 — TEDSWS-524-2 milestone 2 landed

The cluster-size cursor placement bug (C1) is resolved on
`feature/TEDSWS-524-2-review-state` (same branch as milestone 1, fast plan). The
keyset cursor predicate on the derived `cluster_size` field is now applied as a
post-`$addFields` `$match` stage instead of being merged into the stage-1
`query`. Stored-field filters (entity_type, confidence, ever_reviewed,
reviewed_since_placement, etc.) remain in stage 1 — they are still indexable.

Resolved items from this spec:

| Item | Status after TEDSWS-524-2 milestone 2 |
|---|---|
| C1 (cluster_size cursor in wrong stage) | **Resolved.** Cursor predicate runs after `$addFields cluster_size`. |
| C2 (cluster_size + reviewed combined breaks pagination + count) | **Resolved.** The reviewed half was fixed in milestone 1; the cluster_size half is fixed here. |

`cluster_size` remains a derived projection of `cluster_sizes` — no
denormalisation onto the decision row. The trade-off is that cluster-size
ordering still costs a per-page aggregation (one `$lookup` on PK), accepted
at the 3k/day volume.

Coverage added:
- Unit: two pipeline-shape assertions on cursor placement, plus a
  stored-field-filters-stay-in-stage-1 structural check.
- Integration: cluster_size ASC/DESC pagination-across-pages tests (the test
  class that would have caught C1 originally), plus a non-under-fill page-size
  invariant test.
