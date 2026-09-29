# Phase 4 — ClusterSizeIndex Foundation

## Task Specification

**Description:** Introduce a maintained MongoDB projection `cluster_sizes` that tracks the count of decisions per cluster. Drives §1 (cluster-size sort), §4 (CanonicalEntityPreview.cluster_size), §5 (cluster-size stats) in later phases. This phase only builds the foundation — readers come later.

**Acceptance criteria:**
- `ClusterSizeIndex` Protocol defined in domain layer (no Mongo imports).
- `MongoClusterSizeIndex` adapter implementing the protocol with atomic `$inc` upserts.
- `DecisionStoreService.store_decision` calls `shift()` on insert (from=None), on placement change (from=old, to=new), and not at all on unchanged placement.
- Index declaration for `cluster_sizes.size` added to the central bootstrap.
- Backfill script (`src/scripts/backfill_cluster_sizes.py`) — idempotent, `--dry-run`, `--batch-size`.
- Verification script (`src/scripts/verify_cluster_sizes.py`) — exit 0 on consistency, exit 1 on drift.
- All new public symbols have Google docstrings.

**Gherkin scenarios:** 3 scenarios in `test/feature/link_curation_api/cluster_sizes_projection.feature`.

**Layers affected:**
- `domain/` — new `ClusterSizeIndex` Protocol.
- `adapters/` — new `MongoClusterSizeIndex`.
- `services/` — `DecisionStoreService` gets optional `cluster_size_index` injection.
- `entrypoints/` — `app.py` and `dependencies.py` wire the concrete adapter.

---
<!-- implementation-log -->
---

## Implementation Log

**Completed:** 2026-06-01

### What was accomplished

- Created `src/ers/resolution_decision_store/domain/cluster_size_index.py` — clean Protocol with `shift()` and `get_size()`.
- Created `src/ers/resolution_decision_store/adapters/cluster_size_index.py` — `MongoClusterSizeIndex` with single-round-trip `bulk_write` for placement shifts.
- Modified `src/ers/resolution_decision_store/services/decision_store_service.py` — added optional `cluster_size_index: ClusterSizeIndex | None = None` parameter to `DecisionStoreService.__init__()`. Hook calls `shift()` after successful upsert; unchanged-placement short-circuit bypasses it.
- Modified `src/ers/commons/adapters/mongo_client.py` — added `cluster_sizes.size` index to `ensure_indexes()`.
- Modified `src/ers/ers_rest_api/entrypoints/api/app.py` — wired `MongoClusterSizeIndex(db)` into `DecisionStoreService` in the lifespan.
- Modified `src/ers/ers_rest_api/entrypoints/api/dependencies.py` — wired `MongoClusterSizeIndex(db)` in `_get_decision_store_service`.
- Created `test/feature/link_curation_api/cluster_sizes_projection.feature` — 3 Gherkin scenarios.
- Created `test/feature/link_curation_api/test_cluster_sizes_projection.py` — step definitions.
- Created `test/unit/resolution_decision_store/adapters/test_cluster_size_index.py` — 10 adapter unit tests.
- Created `test/unit/resolution_decision_store/services/test_cluster_size_index_hooks.py` — 4 service hook tests.
- Created `src/scripts/backfill_cluster_sizes.py` — idempotent, `--dry-run`, `--batch-size`.
- Created `src/scripts/verify_cluster_sizes.py` — exits 0 on consistency, 1 on drift.

### Key decisions

- **`to_cluster: str | None`** — made `to_cluster` also optional to handle future removal path uniformly in the same primitive.
- **Backward-compatible injection** — `cluster_size_index=None` default means all existing callers (`OutcomeIntegrationService`, test fixtures) work without changes.
- **No lazy import of pymongo in the Protocol** — Protocol is pure Python, pymongo stays confined to the adapter.
- **Index declared in both `MongoClientManager.ensure_indexes()` and `MongoClusterSizeIndex.ensure_indexes()`** — the central bootstrap is the startup path; the adapter method is available for direct use in scripts or integration tests.

### Test counts

- 10 unit tests for the adapter (GREEN).
- 4 unit tests for the service hooks (GREEN).
- 3 Gherkin BDD scenarios (GREEN).
- No regressions: 15 pre-existing async-class failures unchanged.

### Deviations

- None — implementation follows the spec exactly.
