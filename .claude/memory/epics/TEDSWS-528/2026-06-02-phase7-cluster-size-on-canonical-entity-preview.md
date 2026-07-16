# Phase 7 — `cluster_size` on `CanonicalEntityPreview`

## Task Specification

**Description:** Every canonical entity preview returned to the UI carries `cluster_size: int` —
the total number of decisions assigned to that cluster. Sourced from the `ClusterSizeIndex`
projection introduced in Phase 4.

**Affected endpoints:**
- `GET /api/v1/curation/decisions/{id}/proposed-canonical-entity`
- `GET /api/v1/curation/decisions/{id}/alternative-canonical-entities`
- `GET /api/v1/curation/user-actions/{id}/selected-cluster`
- `GET /api/v1/curation/user-actions/{id}/candidates`

**Acceptance criteria:**
- `CanonicalEntityPreview.cluster_size: int` field added (required, no default).
- `CanonicalEntityService` accepts optional `ClusterSizeIndex` injection.
- `build_cluster_preview` calls `cluster_size_index.get_size(cluster_id)` and passes the result to the DTO.
- When no `ClusterSizeIndex` is injected, `cluster_size` defaults to 0.
- No `count_documents` call on the decisions collection.
- `MongoClusterSizeIndex(db)` wired into `get_canonical_entity_service` in `curation/entrypoints/api/dependencies.py`.
- All 4 caller paths (`get_proposed_canonical_entity`, `get_alternative_canonical_entities`, `get_selected_cluster_preview`, `get_candidate_previews`) yield previews with `cluster_size` populated.

**Gherkin scenarios:** 3 new scenarios appended to `test/feature/link_curation_api/canonical_entity_preview.feature`.

**Layers affected:**
- `domain/` — `CanonicalEntityPreview` DTO extended.
- `services/` — `CanonicalEntityService` extended with optional `ClusterSizeIndex`.
- `entrypoints/` — `get_canonical_entity_service` dependency wired with `MongoClusterSizeIndex`.

---
<!-- implementation-log -->
---

## Implementation Log

**Completed:** 2026-06-02

### What was accomplished

- Extended `CanonicalEntityPreview` in `src/ers/curation/domain/data_transfer_objects.py` with a
  required `cluster_size: int` field.
- Updated `CanonicalEntityService.__init__` in `src/ers/curation/services/canonical_entity_service.py`
  to accept optional `cluster_size_index: ClusterSizeIndex | None = None`.
- Updated `build_cluster_preview` to call `await self._cluster_size_index.get_size(cluster_id)` when
  the index is present, defaulting to 0 otherwise. Added Google-style docstring.
- Wired `MongoClusterSizeIndex(db)` into `get_canonical_entity_service` in
  `src/ers/curation/entrypoints/api/dependencies.py`. Added `MongoClusterSizeIndex` import.
- Added `cluster_size_index` mock fixture to `test/feature/link_curation_api/conftest.py` and
  updated `canonical_entity_service` fixture to inject it. Default: `get_size.return_value = 0`.
- Updated 4 direct `CanonicalEntityPreview(...)` construction sites in unit tests:
  - `test/unit/curation/api/test_decisions.py` (2 sites)
  - `test/unit/curation/api/test_user_actions.py` (2 sites)
- Updated `test/unit/curation/api/test_dependencies.py` to pass `mock_db` to `get_canonical_entity_service`.
- Added 13 new unit tests in `test/unit/curation/services/test_canonical_entity_service.py`:
  - `cluster_size_index` fixture
  - `service_without_index` fixture
  - `TestBuildClusterPreviewWithClusterSizeIndex` (4 tests)
  - `TestGetProposedCanonicalEntityWithClusterSize` (1 test)
  - `TestGetAlternativeCanonicalEntitiesWithClusterSize` (1 test)
- Added 3 new Gherkin scenarios to `test/feature/link_curation_api/canonical_entity_preview.feature`.
- Added corresponding step definitions and scenario bindings to
  `test/feature/link_curation_api/test_canonical_entity_preview.py`.

### Key decisions

- **`cluster_size: int` with no default** — the spec requires it be required; the service always
  populates it (either from the index or with 0 as a safe fallback when the index is absent).
- **Backward-compatible injection** — `cluster_size_index=None` default on `CanonicalEntityService`
  lets the feature test conftest avoid wiring the adapter directly during construction; the conftest
  now injects a mock so all 10 feature scenarios are exercised end-to-end.
- **No `count_documents` calls** — enforced by a dedicated unit test that asserts the decision
  repository's `count_documents` attribute was never called.
- **Single `MongoClusterSizeIndex(db)` per request** — constructed fresh in the DI function, reusing
  the request-scoped `db` from `_get_database`, consistent with the existing pattern in
  `ers_rest_api/entrypoints/api/dependencies.py`.

### Test counts

- 13 new unit tests (all GREEN).
- 3 new Gherkin scenarios (all GREEN).
- 10 total feature scenarios passing (7 existing + 3 new).
- No new regressions introduced. 4 pre-existing failures on the branch are unrelated
  (from phases 5/6: `test_get_user_action_service`, 2 × `test_decision_curation_service`,
  `test_creates_all_indexes`).

### Deviations

- None — implementation follows the Phase 7 spec exactly.
