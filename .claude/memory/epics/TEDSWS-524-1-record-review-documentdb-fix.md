# TEDSWS-524-1 §D — `record_review` DocumentDB fix — Design & Plan

Design and implementation plan for the DocumentDB-compatibility hotfix scoped in
`TEDSWS-524-1-specs.md` §D. **Approach: Option A — two classic guarded updates.**

- **Branch:** `hotfix/1.1.0/document-db-compativility`
- **Scope (D7):** surgical adapter fix + a simple unit test. No DocumentDB-in-CI,
  no new E2E. CI-divergence follow-up (D2) left open.
- **Blast radius (D3):** LOW — internal to `MongoDecisionRepository`; signature and
  `bool` contract unchanged.

---

## 1. Problem (recap)

`MongoDecisionRepository.record_review` uses an aggregation-pipeline update
(`update_one(filter, [{"$set": …}])` with `$cond`/`$ifNull`/`$add`), which
Amazon DocumentDB 5.0 does not support. Full analysis, audit, and root cause in
`TEDSWS-524-1-specs.md` §D.

## 2. Behaviour to preserve (the contract)

`record_review(decision_id, action_created_at) -> bool` must, atomically per
call and safe under concurrency:

| Case | Filter guard `flag != True` | Effect | Return |
|---|---|---|---|
| **Fresh** — `action > boundary` | passes | `count += 1`, `flag = True` (slot consumed) | `True` |
| **Stale** — `action <= boundary` | passes | `count += 1`, `flag unchanged` (slot **not** consumed) | `True` |
| **Lost race** — `flag` already `True` | fails | no write | `False` |
| **Absent doc** | fails | no write | `False` |

where `boundary = updated_at if present else created_at`. The stale case
incrementing the counter **without** consuming the slot is a real, intended
subtlety (a stale action reviewed an old placement) and must be kept.

**Key simplification (D4):** because the guard already excludes `flag == True`,
the pipeline's `$cond` else-branch is always `False`; the new flag value is
purely `action > boundary`. No cross-field read is needed beyond the boundary
comparison, which can move into the query filter (the value is a call-time
constant).

## 3. Design — Option A

Replace the single pipeline update with **two classic-operator updates**, the
second issued only if the first does not match. The boundary comparison is
encoded in the filter using the **exact `$or` shape already proven in
`_execute_update`** (flat, DocumentDB-safe, handles `updated_at` null/absent by
falling back to `created_at`).

```python
async def record_review(self, decision_id, action_created_at) -> bool:
    # r1 — fresh path: action strictly after the placement boundary.
    fresh = await self._collection.update_one(
        {
            "_id": decision_id,
            _FIELD_REVIEWED_SINCE_PLACEMENT: {"$ne": True},
            "$or": [
                {_FIELD_UPDATED_AT: {"$lt": action_created_at}},
                {_FIELD_UPDATED_AT: None, _FIELD_CREATED_AT: {"$lt": action_created_at}},
            ],
        },
        {
            "$inc": {_FIELD_PREVIOUS_REVIEW_COUNT: 1},
            "$set": {_FIELD_REVIEWED_SINCE_PLACEMENT: True},
        },
    )
    if fresh.modified_count > 0:
        return True

    # r2 — stale action OR lost race: claim the slot without flipping the flag.
    stale = await self._collection.update_one(
        {"_id": decision_id, _FIELD_REVIEWED_SINCE_PLACEMENT: {"$ne": True}},
        {"$inc": {_FIELD_PREVIOUS_REVIEW_COUNT: 1}},
    )
    return stale.modified_count > 0
```

Notes:
- `$lt` on the stored boundary vs the constant is the inverse of `action >
  boundary`, matching `_execute_update`'s stale filter exactly.
- `{field: None}` matches both null and absent (Mongo/DocumentDB semantics),
  same reliance as `_execute_update` line 485.
- `$ne: True` matches `false`, `null`, and absent — covers legacy docs.
- `$inc` treats an absent counter as `0`, replacing the `$ifNull(...)+1`.

### 3.1 Correctness under concurrency

Each `update_one` is individually atomic under the `$ne: True` guard.

- **Fresh vs fresh (two curators, action after boundary):** both target r1; the
  DB serialises them — the first flips `flag` to `True`, the second's r1 filter
  now fails (`$ne:True`), its r2 filter also fails → returns `False`. Exactly one
  claim. ✓
- **Stale action + concurrent fresh:** both may pass their guards and each
  `$inc` once — identical to the current pipeline design (both pass `$ne:True`);
  the counter reflects both actions and only the fresh one sets the flag. No
  regression. ✓
- **No lost update on the counter:** `$inc` is atomic; interleaved increments
  compose. ✓
- **Round trips:** the common fresh path is **1** round trip; only stale /
  lost-race / absent hit the 2nd.

TOCTOU note: unlike Option C (read-then-write), A reads no state into Python —
the boundary lives in the filter — so there is no stale-boundary window and no
retry loop.

## 4. Test plan (D7 — simple, no E2E)

**Unit** (`test/unit/resolution_decision_store/adapters/test_decision_repository.py`):
1. **Write shape is DocumentDB-safe** — assert `update_one` is called with a
   `dict` update (not a `list`); i.e. no aggregation pipeline. This is the
   regression lock that would have caught the original defect.
2. **Fresh** — action after boundary ⇒ r1 matches; assert `$inc` + `$set
   flag:True`; returns `True`; r2 not called.
3. **Stale** — action at/before boundary ⇒ r1 no match, r2 matches; assert only
   `$inc`, no `$set flag`; returns `True`.
4. **Lost race / absent** — both updates report `modified_count == 0` ⇒ returns
   `False`.
5. **Boundary fallback** — `updated_at` absent uses `created_at` (assert the
   `$or` branch shape).

**Integration** (existing, already on FerretDB — extend, do not add E2E):
`test/integration/resolution_decision_store/test_review_state_lifecycle.py`
already covers fresh-sets-flag and concurrent-only-one-succeeds; confirm they
stay green with the new implementation. FerretDB accepts both forms, so these do
**not** prove DocumentDB compatibility — the unit write-shape assertion (test 1)
is the guard that does. Note this explicitly in the test.

## 5. Task breakdown

| # | Task | Files | Done when |
|---|---|---|---|
| T1 | Replace pipeline update with the two-update Option A implementation | `resolution_decision_store/adapters/decision_repository.py` (`record_review`, ~L640) | Method uses only `$inc`/`$set`/`$ne`/`$or`/`$lt`; docstring updated to describe the two-write flow + preserved semantics |
| T2 | Unit tests 1–5 (§4) | `test/unit/resolution_decision_store/adapters/test_decision_repository.py` | All pass; write-shape assertion present |
| T3 | Verify existing FerretDB lifecycle + idempotency tests green | `test/integration/.../test_review_state_lifecycle.py`, `test/feature/link_curation_api/test_user_action_idempotency.py` | Green, unchanged |
| T4 | Retire / repurpose the misleading pipeline-support integration test | `test/integration/resolution_decision_store/test_aggregation_update_pipeline_support.py` | Either deleted or converted to assert the adapter emits **no** pipeline update (it currently asserts the opposite capability) |
| T5 | `gitnexus_detect_changes` + run adapter + curation suites via Poetry | — | Scope matches expectation; suites green |

## 6. Rollout & risks

- **Migration:** none. Field layout unchanged (`previous_review_count`,
  `reviewed_since_placement` on the decision row). No backfill.
- **Idempotency:** unchanged — the `$ne:True` guard and compensation path in
  `UserActionService._record_or_compensate` are untouched.
- **Perf:** hot path stays 1 round trip; stale/lost-race adds 1 (rare).
- **Residual risk (out of scope, tracked):** CI still runs FerretDB, so future
  pipeline-update regressions remain invisible to integration tests. Mitigated
  here only by the unit write-shape assertion (T2.1). D2 follow-up (a CI-level
  guard, or DocumentDB in CI) remains open.

## 6b. Outcome (2026-07-15 — implemented)

Option A landed on `hotfix/1.1.0/document-db-compativility` via TDD (RED → GREEN).

| # | Task | Result |
|---|---|---|
| T1 | Two-update classic implementation | ✅ `record_review` now issues classic `$inc`/`$set` writes with the flat `$or` boundary filter; docstring rewritten |
| T2 | Unit tests (write-shape lock + fresh/stale/lost-race/absent/boundary) | ✅ RED first (4 failing against pipeline code), then GREEN — 61/61 in the adapter unit file |
| T3 | Existing engine-side + caller tests green | ✅ 9/9 lifecycle integration tests on real FerretDB; 32/32 curation user-action-service unit tests |
| T4 | Retire misleading pipeline-support smoke test | ✅ `test_aggregation_update_pipeline_support.py` deleted (behaviour fully covered by `test_review_state_lifecycle.py`) |
| T5 | Scope check | ✅ `gitnexus detect_changes`: only `MongoDecisionRepository.record_review` in production; LOW risk; no affected processes |

Verification note: the lifecycle suite was run against a locally-started FerretDB
(`ghcr.io/ferretdb/ferretdb:2.7.0` + `postgres-documentdb`), not DocumentDB —
consistent with D7. The unit write-shape assertion (T2.1) is the guard that
actually pins the DocumentDB constraint.

## 7. Out of scope

- DocumentDB-in-CI / real-engine integration (D7).
- Any change to the two-primitive review-state model (ADR-B2N) or the
  materialisation decision from TEDSWS-524-2 milestone 1.
- The A1 cross-module coupling refactor and other unresolved §A items.
