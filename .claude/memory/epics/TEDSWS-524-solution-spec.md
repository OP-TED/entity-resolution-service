# TEDSWS-524 + TEDSWS-522 — Unified Solution Spec

Two tickets, one underlying truth: review status is a *derived* property of `user_actions`, never a stored attribute of the decision.

- **TEDSWS-524** — Sort Resolution Decisions by cluster size; filter by Pending/Reviewed; add cluster-size information to statistics.
- **TEDSWS-522** — On re-access there is no indication a decision was already acted on (list + detail panel); action endpoints are inconsistent (sometimes reject re-actions, sometimes silently accept and re-send to ERE).

---

## Architectural principle

> **A decision is `Reviewed` iff a `user_action` exists for it with `created_at > decision.updated_at` (or `> decision.created_at` when never re-placed); otherwise it is `Pending`.**

This is not a local preference — it is mandated by the architecture:

> *"There is no decision lifecycle status, no pending or reviewed flag, and no curator dominance indicator."* — `entity-resolution-docs › ERSArchitecture/conceptual-model.adoc:223`

> *"This projection is overwritten whenever a new clustering outcome is received from ERE."* — `entity-resolution-docs › AnnexeC-ADRs/adrb2.adoc:30`

> *"User actions … are not authoritative decisions. … The user action log does not modify canonical state."* — `entity-resolution-docs › AnnexeC-ADRs/adrb2.adoc:41-45`

> *"ERS shall process responses idempotently … Late, duplicate, or out-of-order responses are treated as normal behaviour."* — `entity-resolution-docs › AnnexeC-ADRs/adrc2.adoc:51-57`

**Governance shift consequence** (origin of the TEDSWS-522 "previously seen" pain): the canonical URI registry was originally governed by ERS; it now lives in ERE. ERS holds an *overwritten projection* of the latest ERE outcome. The only stable curator trace is the `user_actions` log. The UI must therefore distinguish two questions, served by two different reads against the same log:

| Question | Resets on ERE re-integration? | Served by |
|---|---|---|
| **Q1 — Is the *current placement* reviewed?** | Yes — by design | `?reviewed=true\|false` query parameter on the decisions list (optional; UI's two-tab pattern can also derive it from existing endpoints) |
| **Q2 — Has this *entity* ever been reviewed?** | No | `previous_review_count` counter on `DecisionSummary` (badge) + `GET /curation/user-actions?decision_id={id}` for the full timeline |

No `status` field. No `last_action_at` projected onto `DecisionSummary`. No `DecisionStatus` enum. Status is composed by the UI from two endpoints (filter + history).

---

## Existing ordering conventions (alignment check)

- `DecisionOrdering` (`src/ers/commons/domain/data_transfer_objects.py:7`) uses `"<field>"` for ascending and `"-<field>"` for descending — `confidence_score`, `created_at`, `updated_at`.
- `BaseOrdering` (`src/ers/curation/domain/data_transfer_objects.py:23`) follows the same pattern for other entity listings.

The proposal — `CLUSTER_SIZE_ASC = "cluster_size"`, `CLUSTER_SIZE_DESC = "-cluster_size"` — is identical in shape. No new pattern, no inconsistency.

---

## Proposed solution

### 1. Sort by cluster size — maintained projection (`cluster_sizes`)

On-read aggregation (`$group` by `current_placement.cluster_id`) is **not** chosen, because:

- It performs poorly under load on large decision sets (full group-by per list query).
- It is dialect-bound — porting away from Mongo would require rewriting the pipeline.
- Sort + paginate on a computed column undermines cursor stability.

Instead, maintain a **dedicated read-model collection** `cluster_sizes`:

```
collection: cluster_sizes
{
    _id:        <cluster_id>            # canonical entity URI
    size:       <int>                   # number of decisions whose current_placement.cluster_id == _id
    updated_at: <timestamp>             # last write
}
indexes:
    primary:   _id
    secondary: size                     # for stats percentiles and for the sort pipeline
```

**Maintenance** lives in the **`resolution_decision_store` integration use case** (where ERE outcomes are applied to the projection — the only place placement changes). One small port `ClusterSizeIndex` with two operations:

```python
class ClusterSizeIndex(Protocol):
    async def shift(self, *, from_cluster: str | None, to_cluster: str, by: int = 1) -> None: ...
    async def get_size(self, cluster_id: str) -> int: ...
```

On each integration:
- **New decision** (no prior): `shift(from_cluster=None, to_cluster=new_id, by=+1)`.
- **Placement changed**: `shift(from_cluster=old_id, to_cluster=new_id, by=+1)` (idempotent: decrement old, increment new).
- **Placement unchanged**: no-op.

Both operations are atomic `$inc` upserts in Mongo; portable to any DB that supports atomic counter increments. Bulk-refresh integration applies a `bulkWrite` of the deltas computed for the batch.

**Sort pipeline** in `MongoDecisionRepository.find_with_filters` when `ordering ∈ {CLUSTER_SIZE_ASC, CLUSTER_SIZE_DESC}`:

```
$match     <existing filters>
$lookup    from: cluster_sizes
           localField: current_placement.cluster_id
           foreignField: _id
           as: _cluster_meta
$addFields cluster_size: { $ifNull: [{ $arrayElemAt: ["$_cluster_meta.size", 0] }, 0] }
$project   drop _cluster_meta
$sort      { cluster_size: ±1, _id: -1 }     # _id deterministic tiebreaker (existing pattern, _build_sort:149)
$skip / $limit
```

Single indexed lookup per row, scalar field for sort + pagination. Add `CLUSTER_SIZE_ASC` / `CLUSTER_SIZE_DESC` to `DecisionOrdering` + matching `_SORT_FIELD_MAP` entries.

**One-off backfill** when the projection is first introduced: aggregate the current `decisions` collection once to populate `cluster_sizes`. A `scripts/backfill_cluster_sizes.py` does it via `$group` + bulk upsert.

**Why this is the right call now (vs. when I first rejected it):** the user concern is *performance and cross-DB reliability*, not just YAGNI. A maintained projection is the canonical Cosmic-Python answer to "I need a derived value cheaply on read": maintain it in the same use case that produces the underlying truth. The integrator already knows when placement changes; the increment is one line.

### 2. Pending/Reviewed filter — `?reviewed=true|false` query parameter (no DTO change)

Bind a single boolean query parameter on `GET /api/v1/curation/decisions`:

- `?reviewed=true` → return decisions with a `user_action` since current placement.
- `?reviewed=false` → return decisions with **no** `user_action` since current placement.
- omitted → no filter.

**No new DTO type, no field on `DecisionSummary`, no `DecisionStatus` enum.** The parameter is a thin pass-through at the entrypoint layer that translates into a backend predicate:

```python
# entrypoint (schemas.py — pure parameter binding)
@router.get("/curation/decisions")
async def list_decisions(
    ...,
    reviewed: Annotated[bool | None, Query(description="Filter by current-placement review state.")] = None,
):
    ...
```

The service forwards `reviewed` as a parameter alongside `DecisionFilters` (the existing filter DTO stays untouched). The repository applies a gated `$lookup` stage only when `reviewed is not None`:

```
$lookup    from: user_actions
           let: { decision_id: "$_id", since: { $ifNull: ["$updated_at", "$created_at"] } }
           pipeline: [
               { $match: { $expr: { $and: [
                   { $eq:  ["$decision_id", "$$decision_id"] },
                   { $gt:  ["$created_at", "$$since"] },
               ] } } },
               { $limit: 1 },
               { $project: { _id: 1 } },
           ]
           as: _has_recent_action
$match     reviewed=true  → { _has_recent_action: { $ne: [] } }
           reviewed=false → { _has_recent_action: { $eq: [] } }
$project   drop _has_recent_action
```

The lookup is **never** added when `reviewed is None` and is **never** added on the bulk-sync path (`query_decisions_paginated`), via the same gating mechanism — see §6.

### 3. Per-decision "previously reviewed" — counter on the decision + `decision_id` filter on user-actions

Two complementary surfaces for the two needs identified in TEDSWS-522.

#### 3.1 Counter on the decision — `previous_review_count`

Add a single integer field to the decision document and to `DecisionSummary`:

```python
class DecisionSummary(FrozenDTO):
    ...
    previous_review_count: int = Field(
        default=0,
        description=(
            "Total number of curator actions ever recorded against this decision, "
            "preserved across ERE re-integrations. Drives the UI 'previously reviewed' indicator."
        ),
    )
```

**Maintenance** — single writer, atomic operation:

- In `user_action_service.record_accept` / `record_reject` / `record_assign`, after `_user_action_repository.save(action)`, the service issues an atomic `$inc { previous_review_count: 1 }` on the decision document via the decision-store repository. One extra write per action; constant cost.

- On ERE re-integration, the decision-store integrator **preserves** this field by writing only its own fields (`current_placement`, `candidates`, `updated_at`, `about_entity_mention`) — exactly the existing `$set` behaviour at `decision_repository.py:212-241`. No backfill required at integration time; the counter naturally carries forward.

- One-off backfill for decisions that already have actions in `user_actions`: `scripts/backfill_previous_review_count.py` runs once.

**Why a maintained field beats on-read aggregation here:**

- Returned **on every list row** without a `$lookup` per query (which was the cost concern).
- Reliable: incremented in the same write path that produces the source-of-truth `user_action`. Two atomic writes (action save + counter increment). If the integrator overwrites the decision, the counter is preserved because it lives outside the ERE-owned fields.
- Cross-DB: a plain integer field with an atomic increment — no aggregation pipeline.
- Architecturally clean: the counter is **not a status flag**. It is a *count of historical curator interactions*, which the docs do not forbid (the prohibition is on lifecycle-status fields like Pending/Reviewed, not on cumulative trace counters). The Reviewed/Pending question is *still* answered by derivation from `user_actions` (the `?reviewed` filter via `$lookup`).

#### 3.2 History via existing endpoint — `decision_id` filter on `/curation/user-actions`

Rather than a new sub-resource, extend the existing endpoint with one filter field:

```python
class UserActionFilters(FrozenDTO):
    ...
    decision_id: str | None = None    # NEW
```

UI calls: `GET /api/v1/curation/user-actions?decision_id={id}&ordering=-created_at&limit=<n>` — full `UserActionSummary` payloads, paginated, newest first. No new route, no new DTO; reuses the listing infrastructure that already exists.

Repository: `UserActionCurationRepository.find_with_cursor` adds one `$match` term when `decision_id is not None`. Index on `user_actions.decision_id` is the keystone — same index already required by §2 for the `reviewed` filter.

### 4. Cluster size on `CanonicalEntityPreview` (per-cluster context for review)

Add one optional field:

```python
class CanonicalEntityPreview(FrozenDTO):
    cluster_id: str
    confidence_score: float
    similarity_score: float
    cluster_size: int = Field(
        description="Total number of decisions (entity mentions) assigned to this cluster.",
    )
    top_entities: list[EntityMentionPreview]
```

Populated by `canonical_entity_service.build_cluster_preview` via `ClusterSizeIndex.get_size(cluster_id)` — a single indexed key-value read against the `cluster_sizes` projection introduced in §1. The preview endpoint thus shares one source of truth with the sort pipeline and the stats query; no ad-hoc `count_documents` lives anywhere in the codebase.

Surfaces via the existing endpoints `/curation/decisions/{id}/proposed-canonical-entity` and `/{id}/alternative-canonical-entities`, plus the user-action selected-cluster / candidate preview endpoints — without any signature change at the entrypoint layer.

### 5. Cluster-size distribution in statistics — consistent `cluster_*` naming

Extend `RegistryStatistics` (`src/ers/curation/domain/data_transfer_objects.py:132`) with a coherent prefix. The existing `average_cluster_size` is renamed for consistency; it is the only breaking rename in this Epic and is a small, contained stats-payload change.

```python
class RegistryStatistics(FrozenDTO):
    ...
    cluster_size_average:     float    # was: average_cluster_size (renamed for prefix consistency)
    cluster_size_median:      float    # p50
    cluster_size_p95:         int      # long-tail outliers
    cluster_size_max:         int      # largest cluster
    cluster_singletons_count: int      # clusters of size 1
```

All new + renamed fields start with `cluster_`, making the stats payload self-grouping on the UI side.

Backing from UC-W4:
> *"Statistics may include, per entity type and optionally per time window: total number of Entity Mentions, total number of canonical clusters … number of recent resolution requests."* — `ucw4.adoc:17-26`

**Computation** — read directly from the maintained `cluster_sizes` collection (§1):
- `cluster_singletons_count`: `count_documents({size: 1})` — indexed.
- `cluster_size_max`: one-document `find().sort({size:-1}).limit(1)`.
- `cluster_size_average / median / p95`: a single `$group` + `$bucketAuto` (or `$percentile` on Mongo 7+) over `cluster_sizes` — small collection (one row per cluster), not over the full decisions set.

The shift from "aggregate over `decisions`" to "aggregate over `cluster_sizes`" makes the stats query cost proportional to the number of *clusters*, not the number of *decisions* — a meaningful speedup at scale.

### 6. Idempotency fix — TEDSWS-522 write side

Remove the buggy gate at `src/ers/curation/services/user_action_service.py:42-50`:

```python
async def _check_not_already_curated(self, decision: Decision) -> None:
    since = decision.updated_at or decision.created_at
    already_curated = await self._user_action_repository.has_current_action(
        about_entity_mention=decision.about_entity_mention,
        since=since,
    )
    if already_curated:
        raise AlreadyCuratedError(decision.id)
```

After ERE re-integration, `updated_at` advances → prior actions fall before `since` → exactly one fresh curator action is allowed against the new placement. No second silent acceptance, no inconsistent ERE re-trigger.

---

## Layering / file ownership

| Concern | File |
|---|---|
| `DecisionOrdering` — add `CLUSTER_SIZE_ASC` / `CLUSTER_SIZE_DESC` | `src/ers/commons/domain/data_transfer_objects.py` |
| `RegistryStatistics` — renamed + new `cluster_*` fields | `src/ers/curation/domain/data_transfer_objects.py` |
| `CanonicalEntityPreview.cluster_size` | `src/ers/curation/domain/data_transfer_objects.py` |
| `DecisionSummary.previous_review_count` + `Decision.previous_review_count` | `src/ers/curation/domain/data_transfer_objects.py` (DTO); decision document schema lives in `resolution_decision_store/adapters/decision_repository.py` |
| `ClusterSizeIndex` port (domain protocol) | `src/ers/resolution_decision_store/domain/cluster_size_index.py` (new) |
| `MongoClusterSizeIndex` adapter | `src/ers/resolution_decision_store/adapters/cluster_size_index.py` (new) |
| Integration write hooks (call `ClusterSizeIndex.shift` on insert / placement change) | `src/ers/resolution_decision_store/services/decision_store_service.py` (the use case that applies ERE outcomes — single place that knows when placement changes) |
| `reviewed` query param binding | `src/ers/curation/entrypoints/api/v1/decisions.py` (no DTO field, no enum) |
| `UserActionFilters.decision_id` — extend the existing filter on `/curation/user-actions` | `src/ers/commons/domain/data_transfer_objects.py` (or `src/ers/curation/domain/data_transfer_objects.py` — wherever `UserActionFilters` lives) + filter binding in `entrypoints/api/v1/user_actions.py` + `$match` term in `user_action_repository.find_with_cursor` |
| Read pipeline — cluster-size sort `$lookup` against `cluster_sizes`, gated `$lookup` against `user_actions` for `reviewed` | `src/ers/resolution_decision_store/adapters/decision_repository.py` |
| Atomic `$inc previous_review_count` on every action save | `src/ers/curation/services/user_action_service.py` (in `record_accept` / `record_reject` / `record_assign`) |
| `build_cluster_preview` — read `cluster_size` from `ClusterSizeIndex.get_size` (no ad-hoc `count_documents`) | `src/ers/curation/services/canonical_entity_service.py` |
| Write-guard fix (TEDSWS-522 idempotency) | `src/ers/curation/services/user_action_service.py:42` |
| Statistics aggregations — query `cluster_sizes`, not `decisions` | `src/ers/curation/adapters/statistics_repository.py` |
| One-off backfill scripts | `src/scripts/backfill_cluster_sizes.py`, `src/scripts/backfill_previous_review_count.py` |
| Indexes (verify / declare) | `cluster_sizes._id` (PK), `cluster_sizes.size`, `user_actions.decision_id`, `decisions.current_placement.cluster_id` |

Dependency direction respected: entrypoints → services → domain; adapters → domain. `ClusterSizeIndex` is a domain port (Protocol) — both the integrator (writer) and the read repository (reader) depend on the abstraction, not on the Mongo adapter.

---

## Verified impact (GitNexus, repo `entity-resolution-service`)

| Symbol | Risk | Reading |
|---|---|---|
| `DecisionOrdering` | LOW | 0 upstream callers — safe to extend |
| `RegistryStatistics` | LOW | 1 caller (`get_registry_statistics`) — rename `average_cluster_size` → `cluster_size_average` localised to this single call site + the stats payload contract |
| `CanonicalEntityPreview` | **CRITICAL** (15 processes) | Rating reflects usage breadth, not breakage. Adding a field with a default is non-breaking; only `build_cluster_preview` body changes. |
| `build_cluster_preview` | CRITICAL (15 processes) | Same reading — function body now reads from `ClusterSizeIndex` (one indexed key-value lookup) instead of doing a count. |
| `find_with_filters` | LOW | Shared with `query_decisions_paginated` (bulk sync); the cluster-size `$lookup` against `cluster_sizes` is added only when `ordering` matches the new enum values; the `reviewed` `$lookup` is added only when `reviewed is not None` — both gated, both off by default. |
| `_check_not_already_curated` | **CRITICAL** | 3 direct callers, 20 affected processes. The fix *is* the desired behavioural change for TEDSWS-522. Covered by explicit regression scenarios. |
| `record_accept` / `record_reject` / `record_assign` | HIGH (transitively) | New side-effect: one extra atomic `$inc` on the decision document per call. The action save and the increment must be coordinated; see R8 in risks for the failure-mode handling. |
| `decision_store_service` integration use case | HIGH | New side-effect: calls `ClusterSizeIndex.shift` on placement changes. Localised to the use case; no cross-cutting changes. |

No conflicts with the architecture docs (verified via doc-mining pass — `conceptual-model.adoc`, `adrb2.adoc`, `adrc2.adoc`, `ucw2.adoc`, `ucw4.adoc`). The counter and the cluster-size projection are *traces of curator activity* and *cluster cardinality*, respectively — neither is a decision-lifecycle status, so the prohibition on "pending/reviewed flags" at `conceptual-model.adoc:223` is not engaged.

---

## Tests (BDD + unit)

### Feature: `decision_browsing.feature` — Pending/Reviewed filter & cluster-size sort

```gherkin
Scenario: List decisions pending review (no prior action against current placement)
  Given a decision exists with no user_action recorded since its current placement
  When I GET /api/v1/curation/decisions?reviewed=false
  Then the response includes that decision

Scenario: Filter decisions already reviewed on current placement
  Given a decision with a user_action whose created_at is after its current placement
  When I GET /api/v1/curation/decisions?reviewed=true
  Then the response includes that decision

Scenario: ERE re-integration returns a previously-reviewed decision to Pending
  Given a decision was reviewed (accept) at T1
  And ERE re-integrates a new outcome for the same mention at T2 > T1, advancing updated_at
  When I GET /api/v1/curation/decisions?reviewed=false
  Then the response includes that decision

Scenario: Sort by cluster size ascending then descending
  Given clusters A (size 5), B (size 12), C (size 3) each contain decisions
  When I GET /api/v1/curation/decisions?ordering=cluster_size
  Then the first decision belongs to cluster C
  When I GET /api/v1/curation/decisions?ordering=-cluster_size
  Then the first decision belongs to cluster B

Scenario: Cluster-size sort produces stable pagination under ties
  Given two clusters share the same size
  When I page through /api/v1/curation/decisions?ordering=-cluster_size with cursor
  Then no decision appears twice and none is skipped
```

### Feature: `user_actions_filter_by_decision.feature` — TEDSWS-522 timeline

```gherkin
Scenario: Filter by decision_id returns the entity's full curator timeline
  Given a decision has 3 user_actions recorded at T1 < T2 < T3
  When I GET /api/v1/curation/user-actions?decision_id={id}&ordering=-created_at
  Then the response contains exactly those 3 actions in newest-first order

Scenario: Timeline persists across ERE re-integrations
  Given a decision was reviewed at T1
  And ERE re-integrated the decision at T2 (updated_at advances)
  And the curator reviewed it again at T3
  When I GET /api/v1/curation/user-actions?decision_id={id}
  Then the response includes both pre-T2 and post-T2 actions

Scenario: Decision without user_actions returns an empty page
  Given a decision has no user_actions
  When I GET /api/v1/curation/user-actions?decision_id={id}
  Then the response contains 0 results

Scenario: decision_id filter composes with other filters
  Given a decision has actions of type ACCEPT_TOP and REJECT_ALL
  When I GET /api/v1/curation/user-actions?decision_id={id}&action_type=ACCEPT_TOP
  Then only the ACCEPT_TOP action(s) are returned
```

### Feature: `decision_summary_review_counter.feature` — `previous_review_count`

```gherkin
Scenario: Fresh decision starts at 0
  Given a decision was just integrated from ERE
  When I GET /api/v1/curation/decisions
  Then the row for that decision has previous_review_count = 0

Scenario: Counter increments atomically on each curator action
  Given a decision with previous_review_count = 0
  When the curator records an accept action
  Then the row for that decision has previous_review_count = 1
  When the curator records a reject action (after ERE re-integration)
  Then the row for that decision has previous_review_count = 2

Scenario: Counter is preserved across ERE re-integration
  Given a decision with previous_review_count = 3
  When ERE re-integrates a new outcome for the same mention
  Then the row for that decision still has previous_review_count = 3
  And the current_placement reflects the new ERE outcome

Scenario: Reviewed filter and counter are independent
  Given a decision with previous_review_count = 5 and no action since current placement
  When I GET /api/v1/curation/decisions?reviewed=false
  Then the row appears in the result
  And its previous_review_count = 5
```

### Feature: `decision_canonical_entity_preview.feature` — per-cluster size

```gherkin
Scenario: Proposed canonical entity preview includes cluster size
  Given cluster X has N decisions assigned to it
  When I GET /api/v1/curation/decisions/{id}/proposed-canonical-entity
  Then the response includes "cluster_size": N

Scenario: Alternative canonical entities each carry their own cluster size
  Given alternative clusters Y (size 4) and Z (size 11) for decision D
  When I GET /api/v1/curation/decisions/{id}/alternative-canonical-entities
  Then each item carries its own cluster_size
```

### Feature: `statistics.feature` — cluster-size distribution (renamed fields)

```gherkin
Scenario: Registry statistics expose the cluster-* family
  Given clusters of sizes [1, 1, 1, 4, 7, 12, 50]
  When I GET /api/v1/curation/stats
  Then registry.cluster_singletons_count = 3
  And registry.cluster_size_max = 50
  And registry.cluster_size_median = 4
  And registry.cluster_size_p95 = 50
  And registry.cluster_size_average = (1+1+1+4+7+12+50)/7
  And the deprecated field "average_cluster_size" is absent

Scenario: Statistics are served from cluster_sizes, not from a full decisions scan
  Given the cluster_sizes collection is populated
  When I GET /api/v1/curation/stats
  Then the response is correct
  And the underlying query touches only cluster_sizes
```

### Feature: `cluster_sizes_projection.feature` — maintained projection invariants

```gherkin
Scenario: New decision integration creates or increments the cluster_sizes entry
  Given cluster X has size 4 in cluster_sizes
  When ERE integrates a new decision with current_placement.cluster_id = X
  Then cluster_sizes[X].size = 5

Scenario: Placement change shifts the count
  Given cluster X has size 5 and cluster Y has size 2 in cluster_sizes
  And a decision is currently in cluster X
  When ERE re-integrates that decision into cluster Y
  Then cluster_sizes[X].size = 4
  And cluster_sizes[Y].size = 3

Scenario: Unchanged placement is a no-op
  Given a decision in cluster X with cluster_sizes[X].size = 7
  When ERE re-integrates with the same cluster_id = X
  Then cluster_sizes[X].size = 7

Scenario: Sort by cluster size uses the projection
  Given clusters A (size 5), B (size 12), C (size 3) in cluster_sizes
  When I GET /api/v1/curation/decisions?ordering=-cluster_size
  Then decisions in cluster B come before decisions in cluster A, then C
```

### Feature: `user_action_idempotency.feature` — TEDSWS-522 write side

```gherkin
Scenario: Cannot re-accept a fresh decision (regression for TEDSWS-522)
  Given a decision with updated_at = None
  And an accept action was already recorded
  When I POST /api/v1/curation/decisions/{id}/accept
  Then the response status is 409
  And the error is AlreadyCuratedError

Scenario: New action allowed after ERE re-integration advances updated_at
  Given a decision was accepted at T1
  And ERE re-integrates at T2 (updated_at advances)
  When I POST /api/v1/curation/decisions/{id}/accept
  Then the action is recorded successfully

Scenario: Cannot double-act on the same fresh placement
  Given a decision was rejected at T1
  When I POST /api/v1/curation/decisions/{id}/reject at T2 (no ERE change between)
  Then the response status is 409
```

### Unit tests

- `_check_not_already_curated`: predicate fires regardless of `updated_at` state.
- `ClusterSizeIndex.shift`: idempotent for `from == to`; correctly handles `from_cluster=None` (insert); does not produce negative counts (precondition assertion).
- `MongoClusterSizeIndex.shift`: atomic `$inc` upserts on both keys; verify bulk-write batches commute.
- `record_accept` / `record_reject` / `record_assign`: action save + counter increment are coordinated; verify the action insertion and the `$inc` either both occur or neither does (see R8 mitigation).
- Repository `$lookup` against `cluster_sizes`: stage added only for the cluster-size sort enum values; falls back to `0` for clusters absent from `cluster_sizes`.
- Repository `$lookup` against `user_actions`: stage added only when `reviewed is not None`; omitted on the bulk-sync path.
- `build_cluster_preview`: `cluster_size` read from `ClusterSizeIndex.get_size`; service does **not** call the decisions collection for this.
- `statistics_repository`: percentile, singleton, max, average — verified on synthetic `cluster_sizes` populations including ties and a single-cluster registry.
- No-regression on `query_decisions_paginated`: payload unchanged when neither gating flag is set.

---

## Risks & mitigations (only the reasonable ones)

| Risk | Likelihood | Mitigation |
|---|---|---|
| **R1 — `$lookup` against `user_actions` for the `reviewed` filter** | Low | Indexed `user_actions.decision_id`, inner pipeline `$limit:1` + project `_id` only; gated (only when `reviewed is not None`) and only on the curation path |
| **R2 — `cluster_sizes` drift from `decisions`** (the central correctness risk of the new projection) | Medium → Low | Three layered defences: (a) single writer — only the decision-store integration use case calls `ClusterSizeIndex.shift`; (b) backfill script idempotent and runnable any time; (c) periodic invariant check (`scripts/verify_cluster_sizes.py` — diff aggregation vs projection) wired into a low-frequency CI job or oncall runbook. Strong incentive to keep the writer single — flagged in the docstring on the integrator |
| **R3 — `previous_review_count` drift from `user_actions`** | Low | Single writer (`user_action_service.record_*`); action insert + counter `$inc` performed in close sequence. See R8 for failure-mode handling. Backfill script idempotent. Periodic invariant check (count `user_actions` per decision vs the counter) catches drift if it ever happens |
| **R4 — `_check_not_already_curated` change rated CRITICAL** | N/A — desired | The change *is* the TEDSWS-522 fix. Covered by explicit Gherkin regression. Reversible by re-introducing the `updated_at is not None` gate |
| **R5 — `CanonicalEntityPreview` field addition** | Very low | Pydantic field with default — non-breaking on serialisation. The 15 affected flows are read-paths only. |
| **R6 — Per-decision history pulls full summaries** (one call per detail-panel open) | Low | Lazy-loaded on detail-panel open, not per list row. `decision_id`-indexed query, cursor-paginated. Typical decision has very few historical actions; payload bounded by `limit` |
| **R7 — Semantics discrepancy with product mental model** ("any action" vs "since current placement") | Medium | Now structurally separated by design: `previous_review_count` answers "any action" (lifetime), the `?reviewed` filter answers "since current placement" (current). Both are exposed; the product owner / UX layer chooses which to surface where |
| **R8 — Action save + counter `$inc` not transactional** | Low | The action save is the canonical write; the counter is a denormalised mirror. Failure modes: (a) action save fails ⇒ no increment, consistent; (b) action save succeeds, increment fails ⇒ counter under-reports by 1 until the periodic invariant check or the next backfill run reconciles it. The UI does not block on the counter being correct to the unit. Acceptable. (Optional hardening: a small outbox table to retry failed increments — flagged as future work, not in scope.) |
| **R9 — Stats payload rename breaks consumers** (`average_cluster_size` → `cluster_size_average`) | Low | Single rename in a non-public, internal-curation API surface. Coordinate with the curation webapp release. If a soft migration is preferred, emit both names for one release with a deprecation flag — but not the default recommendation |

---

## Coherence & elegance check

- **Two questions, two surfaces, each served by the cheapest reliable read.**
  - *Q1 — is the current placement reviewed?* → derived on read via gated `$lookup` (cheap, no projection needed because the answer flips on every ERE re-integration anyway).
  - *Q2 — has this entity been touched before?* → answered by a stored counter (`previous_review_count`) maintained at write time, because the answer is needed cheaply on **every** list row.
  - Each question is matched to the technique that fits its read profile and its volatility — neither is forced into the wrong technique.

- **Aligned with existing patterns.** Sort enum follows the established `"field"` / `"-field"` shape. The `decision_id` extension on `UserActionFilters` mirrors how the existing endpoint already accepts `action_type`, `actor`, and `time_range_*` filters. Gating via opt-in pipeline branches mirrors the way `find_with_filters` already conditions on `filters`.

- **Stable read-side cost.** No per-list `$group` over the full decisions set anywhere — the cluster-size sort reads from a maintained projection; the stats query reads from the same projection; the `previous_review_count` is a stored field; the only `$lookup` (for `reviewed`) is gated, single-key, and bounded by page size.

- **Cross-DB portable.** Every read is either an indexed lookup or a scalar field. No DB-specific aggregation tricks. Moving away from Mongo would require porting two atomic `$inc` increments and a `find().sort().limit(1)` — that's it.

- **No status flag anywhere.** The architectural prohibition (conceptual-model.adoc:223) is honoured. `previous_review_count` is a *count*, not a status; the `?reviewed` filter is computed at request time, not stored.

- **Architecturally validated.** Five load-bearing doc passages support the chosen approach (`conceptual-model.adoc:223`, `adrb2.adoc:30`, `adrb2.adoc:41-45`, `adrc2.adoc:51-57`, `ucw4.adoc:17-26`); zero contradictions found.

---

## SOLID & Cosmic Python alignment

**SRP — Single Responsibility.**
- `ClusterSizeIndex` has one responsibility: maintain and serve the per-cluster size projection. Both `MongoClusterSizeIndex` (writer side) and any reader (sort pipeline, stats, preview) talk to the same port.
- `user_action_service` keeps its responsibility — recording curator actions — and gains one side-effect (counter `$inc`) that is *part of recording an action*, not a separate concern.
- `decision_store_service` keeps its responsibility — applying ERE outcomes — and gains one side-effect (`ClusterSizeIndex.shift`) that is *part of applying an outcome*. The integrator already knows when placement changes; this is the right and only place to detect it.
- Statistics, preview, and list endpoints each call a focused service method; no fat aggregator.

**OCP — Open / Closed.**
- `DecisionOrdering` is an enum; new sort criteria (cluster-size) are added by extension, not by editing existing branches. `_SORT_FIELD_MAP` mirrors the same pattern.
- `ClusterSizeIndex` as a Protocol leaves room for alternate implementations (cache, Redis sorted-set, materialised view) without touching its consumers.
- Adding `previous_review_count` extends the projection schema; existing fields remain untouched.

**LSP — Liskov.** No new subclassing relationships introduced. The `MongoClusterSizeIndex` adapter satisfies the `ClusterSizeIndex` Protocol's contract literally.

**ISP — Interface Segregation.** `ClusterSizeIndex` exposes only the two operations its consumers need (`shift`, `get_size`). It does not bundle read-only consumers with write-side concerns by accident — readers depend on `get_size` only.

**DIP — Dependency Inversion.**
- The decision-store integrator depends on the `ClusterSizeIndex` Protocol, not on Mongo. The adapter is injected via the existing dependency-wiring pattern in `entrypoints/api/dependencies.py`.
- `user_action_service` already depends on `UserActionCurationRepository` (a repository abstraction). The new counter increment goes through an additional repository method (`DecisionRepository.increment_review_count(decision_id)`) — the service still talks to abstractions.

**Cosmic Python (Layered architecture).**
- **Domain (`models` + ports)**: `Decision` + `previous_review_count` field; `ClusterSizeIndex` Protocol. No I/O, no framework.
- **Adapters**: `MongoDecisionRepository` (extended), `MongoClusterSizeIndex` (new). Both implement domain ports.
- **Services (use cases)**:
  - `decision_store_service` applies ERE outcomes → calls `ClusterSizeIndex.shift` (write-side projection maintenance).
  - `user_action_service.record_*` → calls action repo + decision-repo counter increment (write-side counter maintenance).
  - `decision_curation_service.list_decisions` → forwards `reviewed` + ordering to the read repository (read-side, no business logic).
  - `statistics_service` → reads from `cluster_sizes` projection (read-side).
  - `canonical_entity_service.build_cluster_preview` → reads `ClusterSizeIndex.get_size` (read-side).
- **Entrypoints (HTTP)**: parameter binding (`reviewed` boolean, `ordering` enum, `decision_id` filter on `/curation/user-actions`), DTO forwarding. Zero business logic.

Dependency direction respected throughout: `entrypoints → services → domain` and `adapters → domain`. No reverse imports.

**Cohesion of the new write path.**
The two new side-effects (cluster-size shift on integration; review-count increment on user action) are each *atomically scoped to a single use case* (one writer per derived value). Single-writer is the property that makes "denormalised projections" tractable in the long run — it's what lets the system stay clean as it grows.

---

## Deliverable order

Ordered so each step is independently shippable and adds value without depending on the next.

1. **Write-guard fix** in `user_action_service._check_not_already_curated` + idempotency Gherkin regression. Closes TEDSWS-522 write side. **Independent of every later step.**
2. **`previous_review_count` on the decision** — schema field (default 0), `DecisionRepository.increment_review_count`, `$inc` call from `user_action_service.record_*`, backfill script, periodic invariant verification script, Gherkin scenarios. Closes the TEDSWS-522 "previously seen" indicator on the list side.
3. **Extend `UserActionFilters` with `decision_id`** — one filter field, reuses the existing `/curation/user-actions` listing. Completes the TEDSWS-522 detail-panel timeline.
4. **`ClusterSizeIndex` port + `MongoClusterSizeIndex` adapter + integrator write hooks + backfill script + verification script.** Foundation for steps 5–7.
5. **`?reviewed=true|false` filter** — entrypoint binding, service forwarding, repository gated `$lookup` against `user_actions`, scenarios.
6. **Cluster-size sort** — `DecisionOrdering` extension, `_SORT_FIELD_MAP` entry, repository `$lookup` against `cluster_sizes`, scenarios.
7. **`CanonicalEntityPreview.cluster_size`** — `build_cluster_preview` reads from `ClusterSizeIndex.get_size`. Scenarios.
8. **Cluster-size distribution stats** — `RegistryStatistics` rename + new fields, `statistics_repository` reads `cluster_sizes`, scenarios. Coordinate the `average_cluster_size` rename with the curation webapp release.

**PR strategy.** Step 1 ships on its own. Steps 2–3 form a TEDSWS-522 follow-up PR. Steps 4–8 form the TEDSWS-524 PR (stack on the 2–3 PR via `--base feature/TEDSWS-522`). Total: three stacked PRs, each independently reviewable.
