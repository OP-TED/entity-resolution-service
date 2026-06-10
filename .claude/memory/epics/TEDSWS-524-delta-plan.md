# TEDSWS-524 / TEDSWS-522 — Implementation Delta Plan

Gap analysis between the target design (`TEDSWS-524-solution-spec.md`) and the
**current implementation** on `hotfix/TEDSWS-524` (baseline shipped in commit
`c654201 feat(curation): cluster-size ordering, stats, and review history`).

This file is the actionable plan: what already exists, what is missing or wrong,
and exactly what to change. The solution spec describes the *target*; this file
describes the *diff*.

---

## Baseline already shipped (`c654201`) — do NOT re-implement

| Capability | Where | State |
|---|---|---|
| `previous_review_count` on `DecisionSummary` + decision doc | `curation/domain/data_transfer_objects.py:94`; `decision_repository.increment_review_count` / `find_review_counts` | ✅ correct |
| Counter `$inc` from curator actions; preserved on ERE re-integration | `user_action_service.record_*`; integrator `$set` excludes the counter | ✅ correct |
| `reviewed=true\|false` filter via `user_actions` `$lookup` (triad join) | `decision_repository._fetch_with_review_filter` | ⚠️ shipped **but buggy** — see D2 |
| `ClusterSizeIndex` port + Mongo adapter | `resolution_decision_store/{domain,adapters}/cluster_size_index.py` | ✅ correct |
| Cluster-size sort (aggregation + keyset cursor over derived `cluster_size`) | `decision_repository._fetch_with_cluster_size_sort` | ✅ correct (filter-before-limit, cursor capture) |
| `CanonicalEntityPreview.cluster_size` from `ClusterSizeIndex` | `canonical_entity_service` | ✅ correct |
| Cluster-size distribution stats over `cluster_sizes` | `curation/adapters/statistics_repository.py` | ✅ correct |
| `decision_id` filter on `/curation/user-actions` (resolves to triad) | `user_action_service._resolve_decision_filter`, `list_user_actions` | ✅ correct & complete (TEDSWS-522 timeline) |

**Join key is already correct in the code**: `user_actions` are matched by the
embedded `about_entity_mention` triad, not a `decision_id` field
(`_fetch_with_review_filter` and `_resolve_decision_filter`). The keystone index
is `user_actions.about_entity_mention`.

---

## Deltas to implement / improve

Ordered by dependency. D1–D2 are the curator-facing four-state work (depends on
the shipped counter); D3 is the write-side fix that makes "Needs revisit" fire;
D4 is a verification-only item.

### D3 — Material-outcome-change short-circuit (write side) — **independent, do first**

**Problem.** `DecisionStoreService.store_decision` short-circuits the write when the
**cluster id** is unchanged:

```python
if existing is not None and existing.current_placement.cluster_id == current.cluster_id:
    return existing   # updated_at NOT bumped, new confidence NOT stored
```

A re-assessment returning the **same cluster with a lower confidence** is swallowed:
`updated_at` never advances (so the decision never becomes "Needs revisit") and the
stale higher confidence keeps displaying. This is live today via
`accept_decision → _publish_reevaluation(proposed_cluster_ids=[current cluster]) → ERE → integrate_outcome → store_decision`.

**Target (spec §6.1).** Short-circuit only on an **identical outcome** —
`current_placement` *and* truncated `candidates` both structurally equal.

**Changes.**
- New domain helper `is_same_outcome(existing, current, candidates) -> bool` in
  `resolution_decision_store/domain/` (value-object comparison, no I/O).
- `store_decision`: replace the `cluster_id` guard with `is_same_outcome(...)` against
  `candidates[:DECISION_STORE_MAX_CANDIDATES]`.

**Blast radius (GitNexus).** `store_decision` = **CRITICAL**, 2 direct callers:
- `integrate_outcome` (ERE result integrator) — the target path.
- `_issue_provisional` (coordinator, on ERE timeout) — **insert path** (`existing is None`),
  so the narrower no-op condition does not change its behaviour. Assert this with a test.
- Downstream: `resolve_single` → `handle_resolve` (9 processes). No signature change.

**Tests.** Extend existing `test_decision_store_service.py` /
`test_store_decision_idempotency.py`; add `decision_store_material_outcome.feature`:
identical replay = no-op; same-cluster confidence change = writes through + bumps
`updated_at`; candidate-reorder = writes through; cluster change = writes through;
provisional issuance unaffected. Confirm `ClusterSizeIndex.shift(X→X)` stays a no-op.

**Acceptance.** Same-cluster confidence drop → `updated_at` advances → row shows
`reviewed_since_placement=false` after D1 lands; identical ERE replay → no write.

---

### D2 — Fix the under-fill pagination bug in the review filter — **fold into D1**

**Problem.** `_fetch_with_review_filter` orders the pipeline
`$match(query) → $sort → $limit(fetch_limit) → $lookup → $match(review)`. It limits
**before** applying the review filter, so a fetched page can be mostly/entirely dropped
by the review `$match`, returning a short page — and when `len(results) <= page_size`
the `next_cursor` is omitted, **terminating pagination prematurely** even when more
matching decisions exist further down.

**Target.** Filter **before** limit — mirror `_fetch_with_cluster_size_sort`, which is
already correct: `$match(query) → $lookup → $addFields → $match(review) → $sort → $limit`.

**Changes.** Reorder the `_fetch_with_review_filter` pipeline. Naturally resolved by D1
(the lookup + `$addFields reviewed_since_placement` must run before the filter `$match`
so the per-row field is always computed and the filter is applied pre-limit).

**Tests.** Pagination scenario: a page where most fetched rows fail the review filter
still fills to `page_size` and yields a `next_cursor`; full traversal returns every
matching decision exactly once (no early termination, no dupes).

**Acceptance.** `?reviewed_since_placement=true|false` paginates completely and stably.

---

### D1 — Four-state review surface (split the boolean into two primitives)

**Problem.** The shipped `reviewed: bool` filter conflates two of the four required
states: `reviewed=false` returns **both** "never reviewed" (no action ever) and
"reviewed but ERE-updated-since" (needs revisit). They differ only by
`previous_review_count`, which the boolean cannot express. And
`reviewed_since_placement` is computed only to *filter* — it is never surfaced as a
**row field**, so the UI cannot render the per-row badge.

**Target (spec §2).** Two orthogonal primitives, UI composes the four states:
- Row fields on `DecisionSummary`: `previous_review_count` (already present) **+ new**
  `reviewed_since_placement: bool` (derived per request via the existing lookup).
- Filter params: `?ever_reviewed=true|false` (counter `$match`) and
  `?reviewed_since_placement=true|false` (the lookup).

**Changes.**
- `DecisionSummary`: add `reviewed_since_placement: bool = False`
  (`curation/domain/data_transfer_objects.py`).
- `decision_repository.find_with_filters` / `_fetch_with_review_filter`:
  - always compute `reviewed_since_placement` via the `user_actions` lookup +
    `$addFields` on the curation path (project it onto the returned document so
    `_from_document` / the summary mapper can read it);
  - gate the review `$match` on `reviewed_since_placement is not None`;
  - add the `previous_review_count` `$match` for `ever_reviewed`;
  - apply both **before** `$sort`/`$limit` (this is D2).
  - mirror into `_fetch_with_cluster_size_sort` so the field is present when sorting
    by cluster size too.
- `decision_curation_service.list_decisions` + `_to_decision_summary`: forward the two
  new flags; set `reviewed_since_placement` on the summary from the repository result.
- Entrypoint `decisions.py`: add `ever_reviewed` and `reviewed_since_placement` query
  params. **Decide the fate of the old `reviewed` param** (see "API contract" below).

**Blast radius (GitNexus).**
- `DecisionSummary` = **LOW**, 1 caller `_to_decision_summary` — trivial field add.
- `list_decisions` = **LOW**, contained.
- `find_with_filters` = LOW (shared with bulk sync; lookup never added on bulk path).

**Tests.** Four-state Gherkin (spec `decision_browsing.feature`): not-reviewed vs
needs-revisit distinguishable; up-to-date; reviewed-more-than-once; both filter params
compose; row carries both primitives. Unit: derivation composes the four states from
`(previous_review_count, reviewed_since_placement)`.

**Acceptance.** UI can filter and render all four states; "never reviewed" and "needs
revisit" are separable.

**API contract.** D1 changes the curation list contract (new row field + new params).
Decide with the curation-webapp owner: (a) replace `reviewed` with the two params, or
(b) keep `reviewed` for one release as an alias of `reviewed_since_placement` and
deprecate. Coordinate the release.

---

### D4 — Verify the TEDSWS-522 timeline (decision_id) — **verification only**

`decision_id` filter on `/curation/user-actions` is shipped and correct
(`_resolve_decision_filter`). Confirm BDD coverage exists for the timeline
(`user_actions_filter_by_decision.feature`); add it if missing. No production change.

---

## Implementation order & PR strategy

1. **D3** — material-outcome short-circuit (independent, write-side; unblocks "Needs revisit").
2. **D1 + D2** — four-state read surface, with the pagination fix folded in.
3. **D4** — verify/add timeline BDD.

PRs on `hotfix/TEDSWS-524`: D3 can ship on its own; D1+D2 as the four-state PR; D4
folds into either. Coordinate the D1 API-contract change with the curation webapp.

## Open questions to resolve before/while implementing

- **API contract for the old `reviewed` param** (D1) — replace vs deprecate-alias. Needs
  the curation-webapp owner's call.
- **`reviewed_since_placement` on the cluster-size sort path** — confirm the field is
  projected in `_fetch_with_cluster_size_sort` too, so rows sorted by cluster size still
  carry the badge.
- **Backfill** — `previous_review_count` is already maintained; confirm whether a
  one-off backfill ran for pre-existing `user_actions`, or schedule it.

## Follow-ups from code review (not blocking the hotfix)

Three parallel reviews (correctness / architecture / tests) found no critical bug and
confirmed the objectives are met. The cheap items were applied (engine-safe
`ever_reviewed=False` via `$in:[0,None]`; single-dump triad mapping; field constants in
the lookup; `ever_reviewed=False` + combined-filter + never-reviewed-row tests). The
following are named for a follow-up ticket:

- **Cross-module data coupling (design smell).** `previous_review_count` lives on the
  `decisions` document (owned by `resolution_decision_store`) but is written by
  `curation`'s `user_action_service`; `find_reviewed_since_placement` reads the
  `user_actions` collection (owned by `curation`) from inside the decision-store adapter.
  Contract-legal (import-linter passes) but encodes one module's schema in the other.
  Consider a read-port abstraction or moving the review-state read to the curation side.
- **Real-DB (FerretDB/DocumentDB) integration coverage.** The new `$in:[0,None]` counter
  match and the `$or`-of-subdocuments in `find_reviewed_since_placement` are only
  exercised against mocks. Add integration tests against the FerretDB testcontainer.
- **`CursorPage.count` ignores the `reviewed_since_placement` filter** (pre-existing for
  the old `reviewed` flag): `count_documents(query)` runs before the user_actions lookup,
  so totals over-report when that filter is set.
- **Concurrent page reads.** `list_decisions` issues `find_by_identifiers`,
  `find_review_counts`, and `find_reviewed_since_placement` sequentially with no data
  dependency — candidates for `asyncio.gather`; the latter two could merge into one port.
- **`$gt` vs `$gte` boundary** for "action since placement" differs between
  `find_reviewed_since_placement`/lookup (`$gt`) and `user_action_repository.has_current_action`
  (`$gte`). Harmless today (an action cannot equal the placement instant); align to prevent a future foot-gun.

## Test commands

```bash
poetry run pytest test/unit/resolution_decision_store/services/test_decision_store_service.py
poetry run pytest test/feature/resolution_decision_store/test_store_decision_idempotency.py
poetry run pytest test/unit/curation -k "review or decision_summary"
poetry run pytest test/feature/link_curation_api/test_decision_browsing.py
```
