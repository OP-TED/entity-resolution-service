# Phase 6 — Cluster-size sort via `$lookup` against `cluster_sizes`

## Task Specification

**Description:** Allow sort by cluster size via `?ordering=cluster_size` and
`?ordering=-cluster_size` on `/api/v1/curation/decisions`. Relies on the
`cluster_sizes` projection introduced in Phase 4.

**Acceptance criteria:**
- `DecisionOrdering` enum extended with `CLUSTER_SIZE_ASC = "cluster_size"` and
  `CLUSTER_SIZE_DESC = "-cluster_size"`.
- `_SORT_FIELD_MAP` extended accordingly.
- `find_with_filters` uses an aggregation pipeline (not `find().sort()`) for
  cluster-size orderings — the field is derived, so `.find()` cannot sort on it.
- Pipeline: `$match` → `$lookup cluster_sizes` → `$addFields cluster_size` →
  `$project` drop `_cluster_meta` → optional review join → `$sort` → `$limit`.
- `$match` (filters) appears before `$lookup` so indexes apply first.
- Cursor pagination works: `cluster_size` integer is captured from the raw
  aggregation document and passed to `encode_cursor` as the sort value.
- Combining `?ordering=-cluster_size&reviewed=false` works — pipeline includes
  both `$lookup cluster_sizes` and `$lookup user_actions`.
- Legacy orderings (`confidence_score`, `created_at`, `updated_at`) continue to
  use the `.find().sort()` path unaffected.
- Google docstrings on all new code.

**Gherkin scenarios added to `decision_browsing.feature`:**
- Sort decisions by cluster size ascending
- Sort decisions by cluster size descending
- Cluster-size sort combined with reviewed filter

**Layers affected:**
- `domain/` — `DecisionOrdering` enum (commons)
- `adapters/` — `MongoDecisionRepository` in `resolution_decision_store`

---
<!-- implementation-log -->
---

## Implementation Log

**Completed:** 2026-06-02

### What was accomplished

- Extended `DecisionOrdering` in
  `src/ers/commons/domain/data_transfer_objects.py` with `CLUSTER_SIZE_ASC` and
  `CLUSTER_SIZE_DESC`.
- Added `_FIELD_CLUSTER_SIZE = "cluster_size"` constant in
  `src/ers/resolution_decision_store/adapters/decision_repository.py`.
- Extended `_SORT_FIELD_MAP` with the two new entries.
- Added `_AGGREGATION_ORDERINGS: frozenset[DecisionOrdering]` to mark which
  orderings require the aggregation path.
- Implemented `_fetch_with_cluster_size_sort` — new private method building the
  pipeline described above. Returns `(list[Decision], last_cluster_size: int | None)`
  so that cursor encoding gets the derived sort value without relying on the domain
  object (which does not carry `cluster_size`).
- Modified `find_with_filters` to route cluster-size orderings through
  `_fetch_with_cluster_size_sort` and encode the cursor with the captured
  `last_sort_raw_value`.
- Extended `_extract_sort_value` docstring to document that derived fields return
  `None` (callers must capture values from raw documents before conversion).
- Added 11 new unit tests in
  `test/unit/resolution_decision_store/adapters/test_decision_repository.py`.
- Added 3 new Gherkin scenarios in
  `test/feature/link_curation_api/decision_browsing.feature`.
- Added 3 scenario bindings + 2 new step defs in
  `test/feature/link_curation_api/test_decision_browsing.py`.

### Key decisions

- **Aggregation-only for cluster-size ordering** — `find().sort()` cannot sort on
  a field that does not exist on the stored document. The aggregation path is used
  unconditionally for these two orderings, even when `reviewed` is None.
- **`last_sort_raw_value` pattern** — rather than `_extract_sort_value` trying to
  read a derived field from a domain object, `_fetch_with_cluster_size_sort`
  captures `doc.get("cluster_size")` from the last raw document before conversion.
  This keeps the cursor encoding clean with no special-casing in the encode/decode
  layer.
- **Strip `cluster_size` before `_from_document`** — the raw document is filtered
  with `{k: v for k, v in doc.items() if k != _FIELD_CLUSTER_SIZE}` before passing
  to `_from_document`. This avoids any unexpected field rejection by Pydantic without
  needing to add `cluster_size` to the Decision model.
- **`$sort` after `$limit` within the cluster-size pipeline** is NOT done — the
  sort must happen before limit so the correct page is selected. The pipeline order
  is `$match → $lookup → $addFields → $project → (optional review stages) → $sort → $limit`.
- **No cursor encoding changes** — `encode_cursor` accepts `float | datetime | None`.
  An integer `cluster_size` serialises as a JSON number and deserialises back as a
  number via `_parse_cursor_sort_value` (not a datetime field, so returned as-is).

### Test counts

- 11 new unit tests (all GREEN).
- 3 new Gherkin scenarios (all GREEN).
- 73 tests total in the two target files (up from 60), no regressions.

### Deviations from spec

- The spec suggested a `_fetch_with_aggregation` shared helper for both the
  cluster-size and reviewed paths. I instead kept them as separate methods
  (`_fetch_with_cluster_size_sort` vs `_fetch_with_review_filter`) because their
  return types differ: cluster-size returns `(decisions, last_sort_value)` while
  review-filter returns `decisions` only. Merging them would complicate both.
- No cursor-pagination encoding changes required (confirmed by analysis).
