# TEDSWS-524 + TEDSWS-522 — Unified Solution Spec

Two tickets, one underlying truth: review status is a *derived* property of `user_actions`, never a stored attribute of the decision.

- **TEDSWS-524** — Sort Resolution Decisions by cluster size; filter by Pending/Reviewed; add cluster-size information to statistics.
- **TEDSWS-522** — On re-access there is no indication a decision was already acted on (list + detail panel); action endpoints are inconsistent (sometimes reject re-actions, sometimes silently accept and re-send to ERE).

---

## Architectural principle

> **Review state is *derived on read* from two independent primitives, never stored:**
> 1. **`previous_review_count`** — total `user_action`s ever recorded against the decision (0 / 1 / >1).
> 2. **`reviewed_since_placement`** — a `user_action` exists whose `created_at > decision.updated_at` (or `> decision.created_at` when never re-placed).
>
> The UI composes the curator-facing states from these two primitives (see table below). There is no stored `status`, no `Pending`/`Reviewed` enum.

**"Current placement" means the full ERE *outcome*, not just the cluster.** `decision.updated_at` advances on any *material outcome change* — a change in `cluster_id`, `confidence_score`, `similarity_score`, or the candidate list — not only when the cluster id changes (see §6.1). This is what lets a re-assessment that returns the *same cluster with lower confidence* re-surface as needing review: `updated_at` moves past the last action's timestamp, so `reviewed_since_placement` flips to `false`.

### Curator-facing states (composed by the UI from the two primitives)

| State | `previous_review_count` | `reviewed_since_placement` | Meaning |
|---|---|---|---|
| **Not reviewed** | `== 0` | `false` (trivially) | No curator action ever recorded |
| **Reviewed, up to date** | `>= 1` | `true` | Reviewed; no ERE outcome change since the review |
| **Reviewed, needs revisit** | `>= 1` | `false` | Reviewed, but a material ERE outcome arrived after the last review |
| **Reviewed more than once, up to date** | `> 1` | `true` | Reviewed repeatedly; current |

The "not reviewed" and "needs revisit" states are **both** `reviewed_since_placement == false` — they are separated *only* by `previous_review_count`. A single boolean cannot express this; the two primitives together can.

This is not a local preference — it is mandated by the architecture:

> *"There is no decision lifecycle status, no pending or reviewed flag, and no curator dominance indicator."* — `entity-resolution-docs › ERSArchitecture/conceptual-model.adoc:223`

> *"This projection is overwritten whenever a new clustering outcome is received from ERE."* — `entity-resolution-docs › AnnexeC-ADRs/adrb2.adoc:30`

> *"User actions … are not authoritative decisions. … The user action log does not modify canonical state."* — `entity-resolution-docs › AnnexeC-ADRs/adrb2.adoc:41-45`

> *"ERS shall process responses idempotently … Late, duplicate, or out-of-order responses are treated as normal behaviour."* — `entity-resolution-docs › AnnexeC-ADRs/adrc2.adoc:51-57`

**Governance shift consequence** (origin of the TEDSWS-522 "previously seen" pain): the canonical URI registry was originally governed by ERS; it now lives in ERE. ERS holds an *overwritten projection* of the latest ERE outcome. The only stable curator trace is the `user_actions` log. The two primitives answer two different questions against that log — one that *resets* on every ERE re-integration (`reviewed_since_placement` — is the *current placement* reviewed?), one that *persists* across them (`previous_review_count` — has this *entity* ever been reviewed?). Neither is a stored lifecycle flag; the four named states live only in the UI's composition layer.

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
$match     <existing filters + cursor condition>
$lookup    from: cluster_sizes
           localField: current_placement.cluster_id
           foreignField: _id
           as: _cluster_meta
$addFields cluster_size: { $ifNull: [{ $arrayElemAt: ["$_cluster_meta.size", 0] }, 0] }
$sort      { cluster_size: ±1, _id: ±1 }     # _id deterministic tiebreaker
$limit     <page_size + 1>
```

**Cursor pagination over a derived sort key.** `cluster_size` is *looked up*, not stored on the decision, so it is not available to encode a `$skip`-free cursor by reading the document alone. The repository captures the `cluster_size` of the **last returned row from the aggregation document** and encodes it (with `_id`) into `next_cursor`; the next page's `$match` reconstructs the `(cluster_size, _id)` keyset predicate. This keeps pagination keyset-based (no `$skip`) and stable under ties. Single indexed lookup per row, scalar field for sort. Add `CLUSTER_SIZE_ASC` / `CLUSTER_SIZE_DESC` to `DecisionOrdering` + matching `_SORT_FIELD_MAP` entries.

**One-off backfill** when the projection is first introduced: aggregate the current `decisions` collection once to populate `cluster_sizes`. A `scripts/backfill_cluster_sizes.py` does it via `$group` + bulk upsert.

A maintained projection is the canonical Cosmic-Python answer to "I need a derived value cheaply on read": maintain it in the same use case that produces the underlying truth. The integrator already knows when placement changes; the increment is one line. This trades a small write-side cost for stable, cross-DB-portable reads.

### 2. Review-state filter & per-row primitive — `reviewed_since_placement` (+ `ever_reviewed` filter)

The curator-facing states (§ Architectural principle) are composed by the UI from **two** primitives. One — `previous_review_count` — is the stored counter of §3.1. The other — `reviewed_since_placement` — is *derived on read* here: a `user_action` exists whose `created_at` is after the current placement boundary `updated_at ?? created_at`.

**Per-row field** — surface `reviewed_since_placement` on `DecisionSummary` so the UI renders the badge without a second call. It is computed in the same aggregation as the list query (the gated `$lookup` below) and is **never stored** — the architectural prohibition on a stored lifecycle status (`conceptual-model.adoc:223`) is honoured because the value is recomputed on every read.

```python
class DecisionSummary(FrozenDTO):
    ...
    previous_review_count: int = Field(default=0, ...)        # §3.1 — 0 / 1 / >1
    reviewed_since_placement: bool = Field(
        default=False,
        description=(
            "True iff a curator action exists whose created_at is after the current "
            "placement boundary (updated_at ?? created_at). Derived on read; with "
            "previous_review_count the UI composes Not-reviewed / Up-to-date / Needs-revisit."
        ),
    )
```

**Two orthogonal filter params** on `GET /api/v1/curation/decisions`, mirroring the two primitives (each optional; UI sends one or both to express a named state):

| Param | Predicate | Used for |
|---|---|---|
| `?ever_reviewed=true\|false` | `previous_review_count > 0` (cheap `$match` on the stored counter) | separates **Not reviewed** (`false`) from the reviewed states |
| `?reviewed_since_placement=true\|false` | the gated `$lookup` below | separates **Up to date** (`true`) from **Needs revisit** (`false`) |

UI mapping: *Not reviewed* → `?ever_reviewed=false`; *Up to date* → `?reviewed_since_placement=true`; *Needs revisit* → `?ever_reviewed=true&reviewed_since_placement=false`. The impossible combo (`ever_reviewed=false & reviewed_since_placement=true`) simply returns empty.

```python
# entrypoint (schemas.py — pure parameter binding)
@router.get("/curation/decisions")
async def list_decisions(
    ...,
    ever_reviewed: Annotated[bool | None, Query(description="Filter on whether any curator action exists.")] = None,
    reviewed_since_placement: Annotated[bool | None, Query(description="Filter on whether a curator action exists since the current placement.")] = None,
):
    ...
```

The service forwards both flags alongside `DecisionFilters` (the existing filter DTO stays untouched). The repository computes `reviewed_since_placement` for the per-row field on the curation path (never on the bulk-sync path `query_decisions_paginated`), and applies the filter `$match` stages only when the corresponding param is set.

**Join key — the `about_entity_mention` triad, not a `decision_id`.** `user_actions` reference a decision by its embedded `about_entity_mention` triad (the same triad that the decision document carries); there is no `decision_id` field on `user_actions`. The correlated `$lookup` therefore joins on the triad and the temporal predicate:

```
$match     <existing filters + cursor condition>
$lookup    from: user_actions
           let: { triad: "$about_entity_mention", since: { $ifNull: ["$updated_at", "$created_at"] } }
           pipeline: [
               { $match: { $expr: { $and: [
                   { $eq:  ["$about_entity_mention", "$$triad"] },
                   { $gt:  ["$created_at", "$$since"] },
               ] } } },
               { $limit: 1 },
               { $project: { _id: 1 } },
           ]
           as: _has_recent_action
$addFields reviewed_since_placement: { $ne: ["$_has_recent_action", []] }   # per-row field
$match     ever_reviewed=true            → { previous_review_count: { $gt: 0 } }
           ever_reviewed=false           → { previous_review_count: { $eq: 0 } }
           reviewed_since_placement=true → { reviewed_since_placement: true }
           reviewed_since_placement=false→ { reviewed_since_placement: false }
$sort      <ordering + _id tiebreaker>
$limit     <page_size + 1>
$project   drop _has_recent_action
```

**Filter before limit (pagination correctness).** The review `$match` must run **before** `$sort`/`$limit`. Applying the limit first and filtering afterwards under-fills the page and can terminate pagination prematurely (a fetched page whose rows are all dropped by the review match yields no `next_cursor` even when more matching decisions exist). The keystone index is `user_actions.about_entity_mention` (shared with §3.2). The `ever_reviewed` filter touches only the stored counter, so it costs nothing extra; the `$lookup` is never added on the bulk-sync path.

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

- On ERE re-integration, the decision-store integrator **preserves** this field by writing only its own fields (`current_placement`, `candidates`, `updated_at`, `about_entity_mention`) in `$set` — never touching `previous_review_count`. No backfill required at integration time; the counter naturally carries forward.

- One-off backfill for decisions that already have actions in `user_actions`: `scripts/backfill_previous_review_count.py` runs once.

This counter is also the primitive that **separates "Not reviewed" from "Needs revisit"** (both have `reviewed_since_placement == false`): only `previous_review_count` distinguishes a decision never touched (`0`) from one reviewed before a later ERE outcome (`> 0`). Together with `reviewed_since_placement` (§2) it yields all four curator-facing states.

**Why a maintained field beats on-read aggregation here:**

- Returned **on every list row** without a `$lookup` per query (which was the cost concern).
- Reliable: incremented in the same write path that produces the source-of-truth `user_action`. Two atomic writes (action save + counter increment). If the integrator overwrites the decision, the counter is preserved because it lives outside the ERE-owned fields.
- Cross-DB: a plain integer field with an atomic increment — no aggregation pipeline.
- Architecturally clean: the counter is **not a status flag**. It is a *count of historical curator interactions*, which the docs do not forbid (the prohibition is on lifecycle-status fields like Pending/Reviewed, not on cumulative trace counters). The "reviewed since current placement" question is *still* answered by derivation from `user_actions` (the `reviewed_since_placement` field via `$lookup`).

#### 3.2 History via existing endpoint — `decision_id` filter on `/curation/user-actions`

Rather than a new sub-resource, extend the existing endpoint with one filter field:

```python
class UserActionFilters(FrozenDTO):
    ...
    decision_id: str | None = None    # NEW
```

UI calls: `GET /api/v1/curation/user-actions?decision_id={id}&ordering=-created_at&limit=<n>` — full `UserActionSummary` payloads, paginated, newest first. No new route, no new DTO; reuses the existing listing infrastructure.

Repository: `UserActionCurationRepository.find_with_cursor` adds one `$match` term filtering on the decision's `about_entity_mention` triad. The entrypoint accepts an opaque `decision_id`; the service resolves it to the decision's triad (one decision read) before querying `user_actions`. The keystone index is `user_actions.about_entity_mention` — the same index §2 uses for the `reviewed_since_placement` lookup.

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

### 6. Write-side contract — when an outcome resets review state

The whole review-state model rests on one invariant: **`decision.updated_at` advances whenever ERE delivers a *materially different* outcome.** Two write-side rules enforce it.

#### 6.1 Store-decision short-circuit keys on the full outcome, not the cluster id

`DecisionStoreService.store_decision` is the single place that applies an ERE outcome to the projection. It is reached on two write paths — the ERE result integrator (`integrate_outcome`) and the coordinator's provisional issuance (`_issue_provisional`) — so its contract must be correct for both.

**Contract:** the write is a no-op **only when the incoming outcome is identical to the stored one** — same `current_placement` *and* same (truncated) `candidates`. Any material change (cluster id, confidence, similarity, or candidate ordering) writes through and bumps `updated_at`.

The outcome is the pair `(current_placement, candidates)`; both are `FrozenDTO` value objects with structural equality. Candidates are truncated to `DECISION_STORE_MAX_CANDIDATES` before persisting, so the comparison uses the truncated incoming list. A domain helper keeps the comparison explicit and unit-testable — no free comparisons scattered in the service:

```python
# resolution_decision_store/domain — value-object comparison, no I/O
def is_same_outcome(existing: Decision, current: ClusterReference, candidates: list[ClusterReference]) -> bool:
    """True iff the stored outcome equals the incoming one (placement + ordered candidates)."""
```

Why outcome-equality and not cluster-equality: a re-assessment that returns the **same cluster with a lower confidence** is exactly the case that must re-surface for review. Keying on the cluster id alone would skip the write, leave `updated_at` stale (so `reviewed_since_placement` stays `true` and the decision never appears as "Needs revisit"), and keep displaying the stale higher confidence — contradicting *"the projection is overwritten whenever a new clustering outcome is received"* (`adrb2.adoc:30`).

Consequences, all desirable:
- A **true idempotent replay** (identical outcome) still no-ops — churn-avoidance and ERE response idempotency (`adrc2.adoc:51-57`) preserved.
- A **same-cluster confidence/candidate change** writes through → `updated_at` bumps → the decision becomes "Needs revisit" and shows fresh confidence.
- `ClusterSizeIndex.shift(from=X, to=X)` is a no-op for the unchanged-cluster case (idempotent for `from == to`), so the cluster-size projection is unaffected by confidence-only changes.
- The provisional path (`_issue_provisional`) is an insert (no `existing`), so the narrower no-op condition does not change its behaviour.

#### 6.2 A curator may act once per placement

Recording a curator action is allowed **iff** no action exists since the current placement (`created_at > updated_at ?? created_at`). After ERE advances `updated_at`, prior actions fall before the boundary and exactly one fresh action is permitted against the new placement; a second action on the *same* placement is rejected (`AlreadyCuratedError`, HTTP 409). This is the same boundary that derives `reviewed_since_placement`, so the read and write sides agree by construction: no second silent acceptance, no inconsistent ERE re-trigger.

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
| Material-outcome-change: outcome-keyed short-circuit (§6.1) + `is_same_outcome` helper | `src/ers/resolution_decision_store/services/decision_store_service.py` (short-circuit) + `src/ers/resolution_decision_store/domain/` (value-object comparison helper) |
| `DecisionSummary.reviewed_since_placement` — derived-on-read bool (per-row primitive) | `src/ers/curation/domain/data_transfer_objects.py` (DTO field) + computed in the read pipeline (`$addFields`) |
| `ever_reviewed` + `reviewed_since_placement` query param binding | `src/ers/curation/entrypoints/api/v1/decisions.py` (no stored field, no enum) |
| `UserActionFilters.decision_id` — extend the existing filter on `/curation/user-actions` | `src/ers/commons/domain/data_transfer_objects.py` (or `src/ers/curation/domain/data_transfer_objects.py` — wherever `UserActionFilters` lives) + filter binding in `entrypoints/api/v1/user_actions.py` + `$match` term in `user_action_repository.find_with_cursor` |
| Read pipeline — cluster-size sort `$lookup` against `cluster_sizes`; `$lookup` against `user_actions` to compute `reviewed_since_placement` (per-row field; gated `$match` for the `reviewed_since_placement` / `ever_reviewed` filters) | `src/ers/resolution_decision_store/adapters/decision_repository.py` |
| Atomic `$inc previous_review_count` on every action save | `src/ers/curation/services/user_action_service.py` (in `record_accept` / `record_reject` / `record_assign`) |
| `build_cluster_preview` — read `cluster_size` from `ClusterSizeIndex.get_size` (no ad-hoc `count_documents`) | `src/ers/curation/services/canonical_entity_service.py` |
| Curator-acts-once write guard (§6.2) | `src/ers/curation/services/user_action_service.py` |
| Statistics aggregations — query `cluster_sizes`, not `decisions` | `src/ers/curation/adapters/statistics_repository.py` |
| One-off backfill scripts | `src/scripts/backfill_cluster_sizes.py`, `src/scripts/backfill_previous_review_count.py` |
| Indexes (verify / declare) | `cluster_sizes._id` (PK), `cluster_sizes.size`, `user_actions.about_entity_mention`, `decisions.current_placement.cluster_id` |

Dependency direction respected: entrypoints → services → domain; adapters → domain. `ClusterSizeIndex` is a domain port (Protocol) — both the integrator (writer) and the read repository (reader) depend on the abstraction, not on the Mongo adapter.

---

## Architectural validation

No conflicts with the architecture docs (verified via doc-mining pass — `conceptual-model.adoc`, `adrb2.adoc`, `adrc2.adoc`, `ucw2.adoc`, `ucw4.adoc`). The counter and the cluster-size projection are *traces of curator activity* and *cluster cardinality*, respectively — neither is a decision-lifecycle status, so the prohibition on "pending/reviewed flags" at `conceptual-model.adoc:223` is not engaged. `reviewed_since_placement` is computed per request (never stored), so it is not a status field either.

> Blast-radius / symbol-level impact analysis for the concrete code changes lives in the implementation delta plan (`TEDSWS-524-delta-plan.md`), not here — this spec describes the target design, not its diff against the current code.

---

## Tests (BDD + unit)

### Feature: `decision_browsing.feature` — review-state filters & cluster-size sort

```gherkin
Scenario: Not-reviewed decisions (no curator action ever)
  Given a decision with previous_review_count = 0
  When I GET /api/v1/curation/decisions?ever_reviewed=false
  Then the response includes that decision
  And the row has reviewed_since_placement = false

Scenario: Reviewed and up to date (action since current placement)
  Given a decision with a user_action whose created_at is after its current placement
  When I GET /api/v1/curation/decisions?reviewed_since_placement=true
  Then the response includes that decision
  And the row has reviewed_since_placement = true

Scenario: Reviewed but needs revisit (ERE update arrived after the last review)
  Given a decision was reviewed (accept) at T1
  And ERE re-integrates a material new outcome for the same mention at T2 > T1, advancing updated_at
  When I GET /api/v1/curation/decisions?ever_reviewed=true&reviewed_since_placement=false
  Then the response includes that decision
  And the row has previous_review_count >= 1
  And the row has reviewed_since_placement = false

Scenario: Not-reviewed and needs-revisit are distinguishable (the boolean would conflate them)
  Given a decision N with previous_review_count = 0 and no action since placement
  And a decision R with previous_review_count = 2 and no action since placement
  When I GET /api/v1/curation/decisions?ever_reviewed=false
  Then the response includes N
  And the response excludes R
  When I GET /api/v1/curation/decisions?ever_reviewed=true&reviewed_since_placement=false
  Then the response includes R
  And the response excludes N

Scenario: Same-cluster confidence drop re-surfaces a reviewed decision as needs-revisit
  Given a decision in cluster X was reviewed (accept) at T1 with confidence 0.92
  When ERE re-integrates the same cluster X at T2 > T1 with confidence 0.55
  Then the decision's updated_at advances to T2
  And the decision's current_placement.confidence_score = 0.55
  And GET /api/v1/curation/decisions?reviewed_since_placement=false includes that decision

Scenario: Reviewed-more-than-once and current
  Given a decision with previous_review_count = 3 and a user_action since its current placement
  When I GET /api/v1/curation/decisions?reviewed_since_placement=true
  Then the response includes that decision
  And the row has previous_review_count = 3
  And the row has reviewed_since_placement = true

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

Scenario: The two primitives are independent (needs-revisit row keeps its lifetime count)
  Given a decision with previous_review_count = 5 and no action since current placement
  When I GET /api/v1/curation/decisions?ever_reviewed=true&reviewed_since_placement=false
  Then the row appears in the result
  And its previous_review_count = 5
  And its reviewed_since_placement = false
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

Scenario: Unchanged cluster keeps the cluster_sizes count (even when confidence changes)
  Given a decision in cluster X with cluster_sizes[X].size = 7
  When ERE re-integrates with the same cluster_id = X but a different confidence
  Then cluster_sizes[X].size = 7
  # The decision document is still rewritten (updated_at bumped, new confidence stored — §6.1),
  # but ClusterSizeIndex.shift(from=X, to=X) is a no-op, so the projection is unchanged.

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

### Feature: `decision_store_material_outcome.feature` — §6.1 short-circuit narrowing

```gherkin
Scenario: Identical outcome replay is an idempotent no-op
  Given a decision in cluster X with confidence 0.80 and candidates [Y, Z]
  When ERE re-integrates the identical outcome (cluster X, confidence 0.80, candidates [Y, Z])
  Then the write is short-circuited
  And updated_at is unchanged

Scenario: Same cluster but changed confidence writes through and bumps updated_at
  Given a decision in cluster X with confidence 0.80
  When ERE re-integrates cluster X with confidence 0.55 at T2
  Then the write is NOT short-circuited
  And updated_at = T2
  And current_placement.confidence_score = 0.55

Scenario: Same cluster but changed candidate ordering writes through
  Given a decision in cluster X with candidates [Y, Z]
  When ERE re-integrates cluster X with candidates [Z, Y]
  Then the write is NOT short-circuited
  And updated_at advances

Scenario: Changed cluster writes through (unchanged behaviour)
  Given a decision in cluster X
  When ERE re-integrates the decision into cluster Y
  Then the write is NOT short-circuited
  And updated_at advances
```

### Unit tests

- `_check_not_already_curated`: predicate fires regardless of `updated_at` state.
- `ClusterSizeIndex.shift`: idempotent for `from == to`; correctly handles `from_cluster=None` (insert); does not produce negative counts (precondition assertion).
- `MongoClusterSizeIndex.shift`: atomic `$inc` upserts on both keys; verify bulk-write batches commute.
- `record_accept` / `record_reject` / `record_assign`: action save + counter increment are coordinated; verify the action insertion and the `$inc` either both occur or neither does (see R8 mitigation).
- Repository `$lookup` against `cluster_sizes`: stage added only for the cluster-size sort enum values; falls back to `0` for clusters absent from `cluster_sizes`.
- Repository `$lookup` against `user_actions`: computes `reviewed_since_placement` on the curation path; `ever_reviewed` / `reviewed_since_placement` `$match` stages applied only when the respective param is not None; whole lookup omitted on the bulk-sync path.
- Review-state derivation: the four curator-facing states are correctly composed from `(previous_review_count, reviewed_since_placement)` — in particular "Not reviewed" (`count==0`) and "Needs revisit" (`count>0 & !since`) are distinguished despite sharing `reviewed_since_placement == false`.
- `is_same_outcome` / short-circuit (§6.1): no-op only when `current_placement` AND truncated `candidates` are structurally equal; writes through on any confidence / similarity / candidate-ordering / cluster change. `shift(from=X, to=X)` invoked as a no-op when cluster unchanged.
- `build_cluster_preview`: `cluster_size` read from `ClusterSizeIndex.get_size`; service does **not** call the decisions collection for this.
- `statistics_repository`: percentile, singleton, max, average — verified on synthetic `cluster_sizes` populations including ties and a single-cluster registry.
- No-regression on `query_decisions_paginated`: payload unchanged when neither gating flag is set.

---

## Risks & mitigations (only the reasonable ones)

| Risk | Likelihood | Mitigation |
|---|---|---|
| **R1 — `$lookup` against `user_actions` for `reviewed_since_placement`** | Low | Indexed `user_actions.about_entity_mention`, inner pipeline `$limit:1` + project `_id` only; only on the curation path (never on bulk sync). `ever_reviewed` adds no lookup (stored-counter `$match`) |
| **R2 — `cluster_sizes` drift from `decisions`** (the central correctness risk of the new projection) | Medium → Low | Three layered defences: (a) single writer — only the decision-store integration use case calls `ClusterSizeIndex.shift`; (b) backfill script idempotent and runnable any time; (c) periodic invariant check (`scripts/verify_cluster_sizes.py` — diff aggregation vs projection) wired into a low-frequency CI job or oncall runbook. Strong incentive to keep the writer single — flagged in the docstring on the integrator |
| **R3 — `previous_review_count` drift from `user_actions`** | Low | Single writer (`user_action_service.record_*`); action insert + counter `$inc` performed in close sequence. See R8 for failure-mode handling. Backfill script idempotent. Periodic invariant check (count `user_actions` per decision vs the counter) catches drift if it ever happens |
| **R4 — `_check_not_already_curated` change rated CRITICAL** | N/A — desired | The change *is* the TEDSWS-522 fix. Covered by explicit Gherkin regression. Reversible by re-introducing the `updated_at is not None` gate |
| **R5 — `CanonicalEntityPreview` field addition** | Very low | Pydantic field with default — non-breaking on serialisation. The 15 affected flows are read-paths only. |
| **R6 — Per-decision history pulls full summaries** (one call per detail-panel open) | Low | Lazy-loaded on detail-panel open, not per list row. `decision_id`-indexed query, cursor-paginated. Typical decision has very few historical actions; payload bounded by `limit` |
| **R7 — Semantics discrepancy with product mental model** ("any action" vs "since current placement") | Medium → resolved | Structurally separated by design into two primitives: `previous_review_count` (lifetime) and `reviewed_since_placement` (current). The UI composes the four named states (Not reviewed / Up to date / Needs revisit / Reviewed-more-than-once). Neither primitive is forced to answer both questions |
| **R8 — Action save + counter `$inc` not transactional** | Low | The action save is the canonical write; the counter is a denormalised mirror. Failure modes: (a) action save fails ⇒ no increment, consistent; (b) action save succeeds, increment fails ⇒ counter under-reports by 1 until the periodic invariant check or the next backfill run reconciles it. The UI does not block on the counter being correct to the unit. Acceptable. (Optional hardening: a small outbox table to retry failed increments — flagged as future work, not in scope.) |
| **R9 — Stats payload rename breaks consumers** (`average_cluster_size` → `cluster_size_average`) | Low | Single rename in a non-public, internal-curation API surface. Coordinate with the curation webapp release. If a soft migration is preferred, emit both names for one release with a deprecation flag — but not the default recommendation |
| **R10 — Short-circuit narrowing increases write volume** (§6.1) | Low | Only *materially changed* outcomes write through; truly identical replays still no-op, so ERE response idempotency (`adrc2.adoc:51-57`) is preserved. Worst case is one extra `find_one_and_update` per genuine outcome change — bounded by the real re-assessment rate. The stale-confidence-display bug it fixes is the stronger reason to make the change |

---

## Coherence & elegance check

- **Two primitives, four states, each served by the cheapest reliable read.**
  - *Is the current placement reviewed?* (`reviewed_since_placement`) → derived on read via the `$lookup` (cheap, no projection needed because the answer flips on every material ERE re-integration anyway).
  - *Has this entity been touched before?* (`previous_review_count`) → a stored counter maintained at write time, because the answer is needed cheaply on **every** list row and separates "Not reviewed" from "Needs revisit".
  - The UI composes the four curator-facing states from these two primitives. Each primitive is matched to the technique that fits its read profile and its volatility — neither is forced to answer both questions.

- **Aligned with existing patterns.** Sort enum follows the established `"field"` / `"-field"` shape. The `decision_id` extension on `UserActionFilters` mirrors how the existing endpoint already accepts `action_type`, `actor`, and `time_range_*` filters. Gating via opt-in pipeline branches mirrors the way `find_with_filters` already conditions on `filters`.

- **Stable read-side cost.** No per-list `$group` over the full decisions set anywhere — the cluster-size sort reads from a maintained projection; the stats query reads from the same projection; the `previous_review_count` is a stored field; the only `$lookup` (for `reviewed_since_placement`) is single-key, bounded by page size, and confined to the curation path.

- **Cross-DB portable.** Every read is either an indexed lookup or a scalar field. No DB-specific aggregation tricks. Moving away from Mongo would require porting two atomic `$inc` increments and a `find().sort().limit(1)` — that's it.

- **No status flag anywhere.** The architectural prohibition (conceptual-model.adoc:223) is honoured. `previous_review_count` is a *count*, not a status; `reviewed_since_placement` is *derived on read* (recomputed every request), not stored. The named states live only in the UI's composition layer.

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
  - `decision_curation_service.list_decisions` → forwards `ever_reviewed` + `reviewed_since_placement` + ordering to the read repository (read-side, no business logic).
  - `statistics_service` → reads from `cluster_sizes` projection (read-side).
  - `canonical_entity_service.build_cluster_preview` → reads `ClusterSizeIndex.get_size` (read-side).
- **Entrypoints (HTTP)**: parameter binding (`ever_reviewed` + `reviewed_since_placement` booleans, `ordering` enum, `decision_id` filter on `/curation/user-actions`), DTO forwarding. Zero business logic.

Dependency direction respected throughout: `entrypoints → services → domain` and `adapters → domain`. No reverse imports.

**Cohesion of the new write path.**
The two new side-effects (cluster-size shift on integration; review-count increment on user action) are each *atomically scoped to a single use case* (one writer per derived value). Single-writer is the property that makes "denormalised projections" tractable in the long run — it's what lets the system stay clean as it grows.

---

## Deliverable order

Ordered so each step is independently shippable and adds value without depending on the next.

1. **Curator-acts-once contract** (§6.2) — review-boundary write guard + idempotency Gherkin regression. Closes the TEDSWS-522 write side. Independent of every later step.
2. **Material-outcome-change short-circuit** (§6.1) — `is_same_outcome` domain helper + outcome-keyed short-circuit in `store_decision`; write-side Gherkin (`decision_store_material_outcome.feature`). Independent; required for "Needs revisit" to fire on same-cluster confidence drops and to fix stale-confidence display.
3. **`previous_review_count` on the decision** — schema field (default 0), counter increment from `user_action_service.record_*`, backfill + invariant-verification scripts, Gherkin. Provides the "ever reviewed" primitive (separates Not-reviewed from Needs-revisit).
4. **Extend `UserActionFilters` with `decision_id`** — one filter field resolving to the triad; reuses the existing `/curation/user-actions` listing. Completes the TEDSWS-522 detail-panel timeline.
5. **`ClusterSizeIndex` port + Mongo adapter + integrator write hooks + backfill + verification scripts.** Foundation for steps 6–8.
6. **Review-state read surface** — `DecisionSummary.reviewed_since_placement` (derived field), `ever_reviewed` + `reviewed_since_placement` filter params, repository `$lookup` with filter-before-limit, four-state scenarios. Depends on step 3 for the counter primitive.
7. **Cluster-size sort** — `DecisionOrdering` extension, `_SORT_FIELD_MAP` entry, repository aggregation + keyset cursor over the derived `cluster_size`, scenarios.
8. **`CanonicalEntityPreview.cluster_size`** — `build_cluster_preview` reads from `ClusterSizeIndex.get_size`. Scenarios.
9. **Cluster-size distribution stats** — `RegistryStatistics` `cluster_*` fields, `statistics_repository` reads `cluster_sizes`, scenarios. Coordinate any stats-field rename with the curation webapp release.

Each step is independently shippable. Steps 1–4 close TEDSWS-522; steps 5–9 deliver TEDSWS-524.
