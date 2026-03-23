# Epic: ERS-EPIC-04 — Resolution Decision Store

## Status
- **Epic ID:** ERS-EPIC-04
- **Component:** #4 — Resolution Decision Store
- **Phase:** Gherkin features complete, ready for implementation
- **Spines:** B (Async Engine Interaction — outcome recording), C (Bulk Sync — delta exposure queries)
- **Last updated:** 2026-03-23
- **Dependencies:** er-spec library (domain models), ERS-EPIC-01 (Request Registry — triad existence)
- **Clarity Gate:** 9.8/10

---

# Part 1 — Specification

**Document type:** Implementation

## 1. Description

The Resolution Decision Store is the persistence layer that maintains the **latest** clustering outcome recorded for each Entity Mention in ERS. It is the ERS projection of ERE-authoritative clustering decisions.

For each Entity Mention (identified by its correlation triad), the store maintains exactly one current Decision record containing the primary cluster assignment, top-N candidate alternatives, and synchronisation timestamps. When a newer outcome arrives, the existing Decision is **atomically replaced** using optimistic concurrency control (timestamp-based staleness detection). There is no historical chain of decisions.

This component is a **pure persistence and query layer**. It does not:
- Make clustering decisions (ERE authority)
- Manage time budgets or provisional identifier derivation logic (Resolution Coordinator, EPIC-06)
- Consume ERE responses or validate contract violations (ERE Result Integrator, EPIC-05)
- Expose REST APIs (EPIC-07)
- Track lookup watermarks or manage refreshBulk state (Request Registry, EPIC-01)

Two upstream writers exist: the Resolution Coordinator (EPIC-06) writes provisional decisions, and the ERE Result Integrator (EPIC-05) writes ERE-confirmed outcomes. Both use the same atomic store operation with staleness detection.

## 2. Glossary

| Term | Definition |
|------|-----------|
| **Correlation Triad** | `(source_id, request_id, entity_type)` from `EntityMentionIdentifier`. Sole correlation and uniqueness key for decisions. |
| **Resolution Decision** | The latest clustering outcome recorded for one Entity Mention. Contains current placement, candidate alternatives, and timestamps. Atomically replaced on each new outcome. |
| **Decision Store** | The MongoDB collection holding exactly one Resolution Decision per triad. A projection repository, not a canonical entity registry. |
| **ClusterReference** | er-spec model containing `cluster_id`, `confidence_score`, `similarity_score`. Used for both `current` and `candidates`. |
| **Staleness Detection** | Timestamp-based optimistic concurrency control. A new outcome is accepted only if its `updated_at` timestamp is strictly greater than the stored `updated_at`. Older or equal timestamps are rejected. |
| **Provisional Singleton Cluster** | A deterministic cluster identifier issued by ERS when ERE does not respond within the execution window. Derivation: `SHA256(concat(source_id, request_id, entity_type))`. Stored as a normal ClusterReference. |
| **Opaque Cursor** | A pagination token that hides internal ordering from callers. Used for cursor-based paginated queries over decisions. |
| **er-spec** | External shared library providing Pydantic domain models used across ERS and ERE. |

## 3. Scope

### In Scope
- `domain/errors.py` — `DecisionStoreError` hierarchy and `DecisionStoreConfig` (using `env_property`)
- MongoDB repository (adapter) extending `MongoDecisionRepository` from `ers.commons.adapters.decision_repository`, adding atomic upsert with staleness condition, triad-based retrieval, and cursor-based paginated queries — stored in the **`decisions` collection** (same collection as the curation module)
- SHA256 provisional cluster ID derivation function (adapter layer utility)
- Thin service layer: `store_decision`, `get_decision_by_triad`, `query_decisions_paginated`
- OpenTelemetry instrumentation at service layer only
- Configurable candidate cardinality cap (default 5) and page size (default 250)

### Out of Scope
- ERE response consumption and contract validation (EPIC-05)
- Time-budget management, provisional identifier issuance orchestration (EPIC-06)
- REST API endpoints (EPIC-07)
- Lookup watermark / refreshBulk delta tracking (EPIC-01 LookupState)
- Historical decision chains or lineage
- User action log / curation (EPIC-09)
- Authentication / authorisation

### Assumptions
1. er-spec models (`EntityMentionIdentifier`, `ClusterReference`) are Pydantic v2 models.
2. MongoDB >= 6.0 is the persistence backend, accessed via `pymongo.asynchronous` through `MongoClientManager` and `BaseMongoRepository` from `ers.commons.adapters`. Do not use `motor` directly.
3. The triad identifying a decision MUST already exist in the Request Registry (EPIC-01). The Decision Store does not enforce this — upstream callers (EPIC-05, EPIC-06) guarantee it.
4. `updated_at` is always a UTC `datetime` and serves as the sole monotonic staleness marker.
5. Candidate lists arrive pre-ordered from ERE; the store truncates to the configurable max but does not re-sort.

## 4. Domain Models

### 4.1 Models from er-spec (used directly — not redefined here)

| Model | Module | Key Fields |
|-------|--------|-----------|
| `Decision` | `erspec.models.core` | `id` (triad_hash), `about_entity_mention` (EntityMentionIdentifier), `current_placement` (ClusterReference), `candidates` (list[ClusterReference]), `created_at`, `updated_at` |
| `EntityMentionIdentifier` | `erspec.models.core` | `source_id`, `request_id`, `entity_type` |
| `ClusterReference` | `erspec.models.core` | `cluster_id`, `confidence_score`, `similarity_score` |

**No local `ResolutionDecisionRecord` class is defined.** `erspec.Decision` is the domain model for this component. It covers all required fields:
- `id` — set to `triad_hash` (SHA256 of triad) on first write; serves as MongoDB `_id`
- `about_entity_mention` — the identifying triad
- `current_placement` — primary cluster assignment
- `candidates` — top-N alternatives (truncated to `max_candidates` on write)
- `created_at` — set once on first insert, never overwritten
- `updated_at` — staleness marker; strictly monotonic

**Pagination:** Use `CursorPage[Decision]` from `ers.commons.domain.data_transfer_objects` (no local `DecisionPage` class needed).

#### DecisionStoreConfig

```python
class DecisionStoreConfig:
    """Configuration for the Decision Store component.

    Uses @env_property decorator from ers.commons.adapters.config_resolver.
    Method names are the environment variable keys (verify exact casing in config_resolver.py).
    Example env vars: ERS_DECISION_STORE_MAX_CANDIDATES=10
    """
    @env_property(default_value="mongodb://localhost:27017")
    def mongodb_uri(self, value: str) -> str: return value

    @env_property(default_value="ers")
    def database_name(self, value: str) -> str: return value

    @env_property(default_value="5")
    def max_candidates(self, value: str) -> int: return int(value)    # top-N candidate cap

    @env_property(default_value="250")
    def default_page_size(self, value: str) -> int: return int(value) # cursor pagination default

    @env_property(default_value="1000")
    def max_page_size(self, value: str) -> int: return int(value)     # hard upper limit
```

- `max_candidates` must be >= 1.
- `default_page_size` must be >= 1 and <= `max_page_size`.
- All values overridable via environment variables.

## 5. Behavioural Specification

### 5.1 Store Decision (Atomic Upsert with Staleness Detection)

```mermaid
flowchart TD
    A[Receive new outcome: triad + ClusterReference + candidates + updated_at] --> B[Truncate candidates to max_candidates]
    B --> C["findOneAndReplace with filter: triad match AND updated_at < new_updated_at"]
    C --> D{Document replaced?}
    D -- Yes --> E[Return updated Decision]
    D -- No match on triad --> F[Insert new Decision with created_at = now]
    F --> G[Return new Decision]
    D -- "Match but staleness rejected (stored >= new)" --> H[Raise StaleOutcomeError]
```

1. The service receives: `about_entity_mention` (EntityMentionIdentifier), `current_placement` (ClusterReference), `candidates` (list[ClusterReference]), `updated_at` (datetime).
2. The service truncates `candidates` to `max_candidates` entries (preserving order).
3. The service delegates to the adapter's `upsert_decision` method.
4. The adapter executes `find_one_and_update` with `$set` + `$setOnInsert`:
   - Filter: `about_entity_mention` fields match the triad AND `updated_at < new_updated_at` (staleness condition)
   - With `upsert=True` for first-time inserts.
   - `$setOnInsert` sets `created_at` and `id` (= `triad_hash`) on first insert only.
5. If the document is replaced or inserted: return the `Decision`.
6. If no replacement occurred (stored `updated_at >= new_updated_at`): raise `StaleOutcomeError`.
7. On first insert, `created_at` is set to `updated_at` value. On subsequent replacements, `created_at` is preserved.

### 5.2 Get Decision by Triad

1. The service receives an `EntityMentionIdentifier`.
2. The adapter queries by the compound `about_entity_mention` fields.
3. Returns `Decision | None`.

### 5.3 Query Decisions Paginated

1. The service receives: optional `cursor` (opaque string), optional `page_size` (int, capped at `max_page_size`).
2. If no cursor: query from the beginning, ordered by `(updated_at ASC, triad_hash ASC)`.
3. If cursor provided: decode using `decode_cursor` from `ers.commons.domain.cursor`; query for records where `(updated_at, _id) > (cursor.last_updated_at, cursor.last_id)`.
4. Fetch `page_size + 1` records to detect whether a next page exists.
5. If `page_size + 1` records returned: build `next_cursor` using `encode_cursor(last.updated_at, last.id)`, return `page_size` records.
6. If fewer records returned: set `next_cursor = None`.
7. Return `CursorPage[Decision]`.

### 5.4 Provisional Cluster ID Derivation

1. The adapter exposes a utility function: `derive_provisional_cluster_id(identifier: EntityMentionIdentifier) -> str`.
2. Algorithm: `SHA256(concat(source_id, request_id, entity_type))` producing a hex digest string.
3. Both ERS and ERE implement the same derivation rule (ADR-A1N).
4. This function is stateless, pure, and deterministic.

## 6. Error Catalogue

| Error Type | Layer | Detection | Response | Log Level |
|------------|-------|-----------|----------|-----------|
| `StaleOutcomeError` | service | `findOneAndReplace` returns None when document exists but staleness condition fails | Raise to caller; do NOT update stored decision | WARN |
| `DecisionNotFoundError` | service | `get_decision_by_triad` returns None when caller expected a result | Return None (adapter); service may wrap contextually | DEBUG |
| `InvalidCursorError` | service | Cursor string fails base64 decode or JSON parse | Raise to caller with descriptive message | WARN |
| `RepositoryConnectionError` | adapter | MongoDB connection failure (`ConnectionFailure`) | Wrap in domain error; propagate to caller | ERROR |
| `RepositoryOperationError` | adapter | MongoDB operation timeout or unexpected error | Wrap in domain error; propagate to caller | ERROR |
| `CandidateCardinalityWarning` | service | Incoming candidates list exceeds `max_candidates` | Truncate silently; log for observability | INFO |

All error types defined in `domain/errors.py`. Each inherits from a base `DecisionStoreError`.

## 7. Task Breakdown and Roadmap

### Task 1: Define Domain Errors and Configuration
**Layer:** `domain/`
**Dependencies:** er-spec library installed
**Description:**
- **No local domain model** — `erspec.Decision` is used directly throughout this component. Do not define `ResolutionDecisionRecord` or any equivalent class.
- Create `domain/errors.py` with base `DecisionStoreError` (inherits `ApplicationError` from `ers.commons.services.exceptions`) and subclasses: `StaleOutcomeError`, `DecisionNotFoundError`, `InvalidCursorError`, `RepositoryConnectionError`, `RepositoryOperationError`.
- Create `domain/config.py` with `DecisionStoreConfig` using the `@env_property` decorator from `ers.commons.adapters.config_resolver` (not Pydantic `env_prefix`). Method names become the environment variable keys (verify exact casing by reading `config_resolver.py`).

**Acceptance Criteria:**
- All models instantiate with valid data; frozen where appropriate.
- `DecisionStoreConfig()` produces valid defaults.
- Invalid `max_candidates` (0, -1), invalid `default_page_size` (0, > max_page_size) rejected by validation.
- Environment variables override defaults.
- All error classes instantiable with message string; inherit from `DecisionStoreError`.

### Task 2: Lift Cursor Helpers to MongoDecisionRepository (commons)
**Layer:** `ers.commons.adapters`
**Dependencies:** None (pure refactor, no new domain code)
**Description:**
`_build_cursor_condition` and `_parse_cursor_sort_value` in `MongoDecisionCurationRepository`
are generic MongoDB cursor-seek utilities with no dependency on curation-specific types. The new
`MongoDecisionStoreRepository` (Tier 1) needs the same helpers, but importing from `ers.curation`
(Tier 3) is forbidden by import-linter. Lifting them to the commons base class is the only DRY
solution that respects the tier boundary.
- Add `_build_cursor_condition`, `_parse_cursor_sort_value`, `_DATETIME_FIELDS` to `MongoDecisionRepository` in `ers.commons.adapters.decision_repository`.
- Remove those methods from `MongoDecisionCurationRepository` in `ers.curation.adapters.decision_repository` — it will inherit them unchanged.
- Update any reference to `self._DATETIME_SORT_FIELDS` → `self._DATETIME_FIELDS` in the curation repo.

**Acceptance Criteria:**
- All existing curation unit tests pass without modification.
- `MongoDecisionCurationRepository._build_cursor_condition` is accessible (via inheritance) and behaviour is identical.

### Task 3: Implement MongoDB Adapter
**Layer:** `adapters/`
**Dependencies:** Tasks 1 + 2
**Description:**
- Create `adapters/decision_repository.py` with `MongoDecisionStoreRepository`.
  - Extends `MongoDecisionRepository` from `ers.commons.adapters.decision_repository` (which already uses `erspec.Decision`, `_collection_name = "decisions"`, `_id_field = "id"`). This is a **parallel sibling** to `MongoDecisionCurationRepository` — both extend the same base, both operate on the `decisions` collection.
  - Inherits `_build_cursor_condition`, `_parse_cursor_sort_value`, `_DATETIME_FIELDS` from base (added in Task 2). Do NOT re-implement these.
  - Adds methods beyond the base class: `upsert_decision`, `find_by_triad`, `query_paginated`, `ensure_indexes`.
  - `upsert_decision` uses `find_one_and_update` with `$set` + `$setOnInsert`:
    - Filter: `{"_id": triad_hash, "updated_at": {"$lt": new_updated_at}}` with `upsert=True`.
    - `$setOnInsert`: sets `id = triad_hash` and `created_at` on first insert only.
    - `$set`: updates `current_placement`, `candidates`, `updated_at`.
    - Returns `AFTER` document. If result is `None`, detect staleness by checking if the triad exists.
  - `find_by_triad`: calls `find_by_id(triad_hash)` — since `Decision.id = triad_hash`, this is a direct `_id` lookup.
  - `query_paginated`: cursor pagination ordered by `(updated_at ASC, _id ASC)`. Calls `self._parse_cursor_sort_value` and `self._build_cursor_condition` from base. Uses `encode_cursor(decision.updated_at, decision.id)` / `decode_cursor`. Returns `CursorPage[Decision]`.
  - `ensure_indexes`: compound index on `(updated_at, _id)` for pagination performance.
- Create `adapters/provisional_id.py` with `derive_provisional_cluster_id(identifier: EntityMentionIdentifier) -> str`.
  - Implements `SHA256(concat(source_id, request_id, entity_type))` by reusing `SHA256ContentHasher` from `ers.commons.adapters.hasher`. Do NOT re-implement SHA256.
  - Dual purpose: provisional cluster ID and the `Decision.id` value set on first insert.
- Map all `pymongo` exceptions to domain error types (`ConnectionFailure` → `RepositoryConnectionError`, `OperationFailure` → `RepositoryOperationError`/`StaleOutcomeError`).

**Acceptance Criteria:**
- `upsert_decision` atomically replaces only when `new_updated_at > stored_updated_at`.
- `upsert_decision` inserts on first occurrence (sets `created_at`).
- `upsert_decision` preserves `created_at` on replacement.
- `find_by_triad` returns None for non-existent triads.
- `query_paginated` returns correct pages with opaque cursors.
- `derive_provisional_cluster_id` produces deterministic SHA256 hex digest.
- MongoDB exceptions never leak (always wrapped in domain errors).

### Task 4: Implement Service Layer
**Layer:** `services/`
**Dependencies:** Tasks 1 + 3
**Description:**
- Create `services/decision_store_service.py` with `DecisionStoreService`.
- Constructor: `__init__(self, repository: MongoDecisionStoreRepository, config: DecisionStoreConfig)`.
- Class methods (not traced): `store_decision`, `get_decision_by_triad`, `query_decisions_paginated`.
- Also expose **module-level public API functions** decorated with `@trace_function` from `ers.commons.adapters.tracing`. These are the API boundary — tracing belongs here, not on class methods. Pattern identical to `ers.request_registry.services.request_registry_service`.
  - `@trace_function(span_name="decision_store.store_decision")` async def store_decision(identifier, current, candidates, updated_at, service) -> Decision
  - `@trace_function(span_name="decision_store.get_decision_by_triad")` async def get_decision_by_triad(identifier, service) -> Decision | None
  - `@trace_function(span_name="decision_store.query_paginated")` async def query_decisions_paginated(service, cursor, page_size) -> CursorPage[Decision]
- Register OTel span attribute extractors in `adapters/span_extractors.py` using `register_span_extractor` from `ers.commons.adapters.tracing`. Import at app startup only (not at module level in other packages).
- Structured logging at WARN (stale outcome, candidate truncation).
- `DecisionStoreConfig` is instantiated using `@env_property` (not Pydantic constructor — see Task 1).

**Acceptance Criteria:**
- `store_decision` truncates candidates to `max_candidates`.
- `store_decision` propagates `StaleOutcomeError` from adapter.
- `query_decisions_paginated` decodes opaque cursor; raises `InvalidCursorError` on malformed input.
- `query_decisions_paginated` caps `page_size` at `max_page_size`.
- OTel spans created with correct attributes.

### Task 5: Unit Tests
**Layer:** `tests/`
**Dependencies:** Tasks 1-4
**Description:**
- Unit tests for all domain models, adapter (mock `AsyncDatabase`/collection via `MagicMock`/`AsyncMock`), service (mock repository via `create_autospec(MongoDecisionStoreRepository)`), and provisional ID derivation.
- Minimum 90% coverage on all modules.

**Acceptance Criteria:** All test cases from Section 8 pass. Coverage >= 90%.

### Task 6: Integration Tests
**Layer:** `tests/`
**Dependencies:** Tasks 1-4
**Description:**
- Integration tests using real MongoDB (testcontainers or docker-compose).
- Full lifecycle: store, retrieve, replace with staleness, paginated query, concurrent upsert.

**Acceptance Criteria:** All integration test cases from Section 8 pass. Tests skippable if MongoDB unavailable (pytest mark).

### Task 7: Gherkin Features
**Layer:** `tests/feature/`
**Dependencies:** Tasks 1-4
**Description:** Feature files for store, staleness rejection, pagination, and provisional ID scenarios. Step definitions calling the service.

**Acceptance Criteria:** All Gherkin scenarios from Section 13 pass via pytest-bdd.

## Roadmap
- [x] Task 0: EPIC corrections + implementation log (2026-03-23)
- [ ] Task 1: Define Domain Errors and Configuration (domain/)
- [ ] Task 2: Lift cursor helpers to MongoDecisionRepository (commons refactor)
- [ ] Task 3: Implement MongoDB Adapter (adapters/)
- [ ] Task 4: Implement Service Layer (services/)
- [ ] Task 5: Unit Tests (tests/unit/)
- [ ] Task 6: Integration Tests (tests/integration/)
- [ ] Task 7: Gherkin Features (tests/feature/)

## 8. Test Case Specifications

### Unit Tests

| Test ID | Component | Input | Expected Output | Edge Cases |
|---------|-----------|-------|-----------------|------------|
| TC-001 | DecisionStoreConfig | Default constructor | Valid config (max_candidates=5, page_size=250) | N/A |
| TC-002 | DecisionStoreConfig | max_candidates=0 | ValidationError | max_candidates=-1 |
| TC-003 | DecisionStoreConfig | default_page_size > max_page_size | ValidationError | default_page_size=0 |
| TC-004 | DecisionStoreConfig | env vars set | Config picks up env values | Partial env override |
| TC-005 | Error hierarchy | Instantiate each error | All inherit from DecisionStoreError | str(error) includes message |
| TC-006 | Adapter: upsert (new) | Non-existent triad + mock | find_one_and_update with upsert=True; created_at set | N/A |
| TC-007 | Adapter: upsert (replace) | updated_at > stored + mock | Succeeds; created_at preserved | Timestamps differ by 1ms |
| TC-008 | Adapter: upsert (stale) | updated_at <= stored + mock | Raises StaleOutcomeError | Equal timestamps |
| TC-009 | Adapter: find_by_triad (found) | Existing triad + mock | Returns Decision | N/A |
| TC-010 | Adapter: find_by_triad (not found) | Non-existent triad | Returns None | All fields present but no match |
| TC-011 | Adapter: query_paginated (first) | No cursor, page_size=2, 5 records | Returns 2 items + next_cursor | page_size=0 raises error |
| TC-012 | Adapter: query_paginated (last) | Cursor near end, 1 remaining | Returns 1 item + next_cursor=None | Exactly page_size remaining |
| TC-013 | Adapter: query_paginated (empty) | No records | Returns 0 items + next_cursor=None | N/A |
| TC-014 | derive_provisional_cluster_id | Known triad ("A","B","C") | Deterministic SHA256 hex of "ABC" | Unicode in triad fields |
| TC-015 | Service: store (truncation) | 8 candidates, max=5 | Truncated to 5 | Exactly 5 (no-op); 0 candidates |
| TC-016 | Service: store (stale) | Adapter raises StaleOutcomeError | Propagated unchanged | N/A |
| TC-017 | Service: query (bad cursor) | Malformed base64 | Raises InvalidCursorError | Empty string; valid b64 bad JSON |
| TC-018 | Service: query (cap) | page_size=5000, max=1000 | Capped to 1000 | page_size=None uses default |
| TC-019 | Service observability | Valid store call | OTel span with source_id, cluster_id | Error: span records exception |

### Integration Tests

| Test ID | Flow | Setup | Verification | Teardown |
|---------|------|-------|--------------|----------|
| IT-001 | Store and retrieve | Start MongoDB; ensure indexes | Store, retrieve by triad, verify all fields | Drop collection |
| IT-002 | Staleness rejection | Store with T1 | Store with T0 < T1 raises StaleOutcomeError; original unchanged | Drop collection |
| IT-003 | Atomic replacement | Store T1, store T2 > T1 | created_at preserved; updated_at=T2; candidates replaced | Drop collection |
| IT-004 | Cursor pagination | Insert 10 decisions | page_size=3: get 4 pages (3+3+3+1); ordering correct | Drop collection |
| IT-005 | Concurrent upsert | Start MongoDB | 5 concurrent upserts T1..T5; final state has T5 | Drop collection |
| IT-006 | Provisional ID consistency | N/A | 1000 calls same input; all identical | N/A |

## 9. Anti-Patterns (DO NOT)

| Don't | Do Instead | Why |
|-------|-----------|-----|
| Store historical decision chains or lineage | Atomically replace the single decision per triad | Architecture mandates latest-only projection (Section 9.3). History belongs in ERE. |
| Implement staleness with separate read+write | Use `findOneAndReplace` with staleness condition as single atomic operation | Separate read-then-write is a race condition. |
| Import `motor` or `pymongo` in the service layer | Keep all MongoDB imports in `adapters/` only | DIP: services depend on adapter abstraction, not infrastructure. |
| Track lookup watermarks in the Decision Store | Lookup tracking belongs in Request Registry (EPIC-01) | SRP: Decision Store stores decisions; exposure tracking is separate. |
| Reinterpret or re-score ClusterReference values | Store confidence_score and similarity_score exactly as received | ERS is a projection layer; scoring authority belongs to ERE. |
| Put OTel spans or logging in the adapter layer | Keep all observability in `DecisionStoreService` | Architectural constraint: observability at service level only. |
| Create models duplicating er-spec models | Import from `erspec.models` | Reuse er-spec models exclusively; avoid shadow identity. |
| Use offset-based pagination | Use cursor-based pagination with opaque tokens | Offset has O(n) skip cost and inconsistency under concurrent writes. |
| Allow `updated_at` equal for acceptance | Accept only strictly greater timestamps | Equal timestamps = duplicate delivery; must reject for monotonicity. |
| Validate triad existence in Request Registry from Decision Store | Trust upstream callers (EPIC-05, EPIC-06) | SRP: cross-store validation is the coordinator's job. |

## 10. Architectural Constraints

1. **ERE Authority:** Decision Store mirrors outcomes. Does not create, redefine, or enrich identity.
2. **Latest-Only Projection:** Exactly one Decision per triad. No historical chain.
3. **Atomic Replacement:** `findOneAndReplace` with staleness condition. No read-then-write.
4. **Timestamp Monotonicity:** `updated_at` strictly monotonic. Accept only if `new > stored`.
5. **Observability at Service Level:** OTel spans and logs in `DecisionStoreService` only.
6. **Reuse er-spec Models:** Only local technical models (cursor, config, errors) defined here.
7. **Layering:** `models/` -> `adapters/` -> `services/`. No reverse dependencies.
8. **No Cross-Store Queries:** Decision Store does not query Request Registry.

## 11. Dependencies and Integration Points

| Dependency | Type | Provides | Status |
|-----------|------|----------|--------|
| **er-spec** | Library | `EntityMentionIdentifier`, `ClusterReference` | Available |
| **pymongo** | Package (>= 4.6, includes `pymongo.asynchronous`) | Async MongoDB driver + operations + exceptions | Available |
| `ers.commons.adapters.repository` | Internal | `BaseMongoRepository[T,ID]`, `AsyncReadRepository`, `AsyncWriteRepository` | Available |
| `ers.commons.adapters.mongo_client` | Internal | `MongoClientManager` — lifecycle + index management | Available |
| `ers.commons.adapters.hasher` | Internal | `SHA256ContentHasher` — SHA256 hex digest | Available |
| `ers.commons.domain.cursor` | Internal | `encode_cursor`, `decode_cursor`, `InvalidCursorError` | Available |
| **Pydantic** | Package (>= 2.0) | Model definitions, config validation | Available |
| **OpenTelemetry** | Package | Tracing spans | Available |
| MongoDB | Infrastructure (>= 6.0) | Persistence backend | Available |

### Downstream Consumers
| Consumer | What It Uses | Epic |
|----------|-------------|------|
| ERE Result Integrator | `store_decision()` | ERS-EPIC-05 |
| Resolution Coordinator | `store_decision()` (provisional), `get_decision_by_triad()` | ERS-EPIC-06 |
| Bulk Lookup API | `query_decisions_paginated()` | ERS-EPIC-07 |
| Single Lookup API | `get_decision_by_triad()` | ERS-EPIC-07 |
| Link Curation | `get_decision_by_triad()` (read candidates) | ERS-EPIC-09 |

## 12. Concrete Examples

### Example 1: First decision (provisional singleton)
```json
{
  "id": "a3f5c8d9e1b2...",
  "about_entity_mention": {"source_id": "TEDSWS", "request_id": "324fs3r345vx", "entity_type": "http://www.w3.org/ns/org#Organization"},
  "current_placement": {"cluster_id": "a3f5c8d9e1b2...", "confidence_score": 1.0, "similarity_score": 1.0},
  "candidates": [{"cluster_id": "a3f5c8d9e1b2...", "confidence_score": 1.0, "similarity_score": 1.0}],
  "created_at": "2026-01-14T12:34:56Z",
  "updated_at": "2026-01-14T12:34:56Z"
}
```
Note: `id` = `SHA256(concat("TEDSWS", "324fs3r345vx", "http://www.w3.org/ns/org#Organization"))`. Singleton candidates.

### Example 2: ERE replaces provisional
```json
{
  "id": "a3f5c8d9e1b2...",
  "about_entity_mention": {"source_id": "TEDSWS", "request_id": "324fs3r345vx", "entity_type": "http://www.w3.org/ns/org#Organization"},
  "current_placement": {"cluster_id": "ere-cluster-7a2b", "confidence_score": 0.92, "similarity_score": 0.88},
  "candidates": [
    {"cluster_id": "ere-cluster-7a2b", "confidence_score": 0.92, "similarity_score": 0.88},
    {"cluster_id": "ere-cluster-4c5d", "confidence_score": 0.85, "similarity_score": 0.79},
    {"cluster_id": "ere-cluster-9e1f", "confidence_score": 0.71, "similarity_score": 0.65}
  ],
  "created_at": "2026-01-14T12:34:56Z",
  "updated_at": "2026-01-14T12:35:02Z"
}
```
Note: `created_at` preserved. `updated_at` advanced. 3 candidates from ERE.

### Example 3: Stale outcome rejected
- Stored: `updated_at = 2026-01-14T12:35:02Z`. Incoming: `updated_at = 2026-01-14T12:34:58Z`.
- Result: `StaleOutcomeError`. Stored decision unchanged.

## 13. Gherkin Feature Outline

At `tests/feature/decision_store/`:

### Feature: Store Resolution Decision

| Scenario | Description |
|----------|-------------|
| Store first decision for a triad | New triad gets decision with created_at = updated_at |
| Replace decision with newer outcome | created_at preserved; updated_at advanced |
| Reject stale outcome | Older timestamp raises StaleOutcomeError; stored unchanged |
| Reject outcome with equal timestamp | Same timestamp raises StaleOutcomeError |
| Store provisional singleton decision | SHA256-derived cluster_id stored as normal ClusterReference |
| Truncate excess candidates | 8 candidates truncated to max_candidates=5; order preserved |

### Feature: Retrieve Resolution Decision

| Scenario | Description |
|----------|-------------|
| Retrieve existing decision by triad | Returns Decision |
| Retrieve non-existent triad | Returns None |

### Feature: Paginated Decision Query

| Scenario | Description |
|----------|-------------|
| First page of decisions | Returns page_size items + next_cursor |
| Continue with cursor | Second page starts after first page's last item |
| Last page (partial) | Returns remaining items + next_cursor=None |
| Empty collection | Returns 0 items + next_cursor=None |
| Invalid cursor token | Raises InvalidCursorError |
| Page size exceeds maximum | Capped to max_page_size silently |

## 14. References

| Topic | Location | Section |
|-------|----------|---------|
| Decision Store conceptual model | `docs/modules/ROOT/pages/ERSArchitecture/conceptual-model.adoc` | Section 9.1 (#2) and 9.3 |
| Spine B: Async outcome integration | `docs/modules/ROOT/pages/ERSArchitecture/spine-b.adoc` | Section 8.3 |
| ADR-A1N: Identifier Space | `docs/modules/ROOT/pages/AnnexeC-ADRs/adra1.adoc` | SHA256 derivation, cluster-as-canonical |
| ADR-A2N: Provisional Identifier | `docs/modules/ROOT/pages/AnnexeC-ADRs/adra2.adoc` | Provisional singleton lifecycle |
| UC-W1: Resolve Entity Mention | `docs/modules/ROOT/pages/AnnexeB-UseCases/ucw1.adoc` | Decision recording |
| er-spec core models | `https://github.com/OP-TED/entity-resolution-spec` | `erspec.models.core` |
| ERS-EPIC-01 Request Registry | `.claude/memory/epics/ers-epic-01-request-registry/EPIC.md` | Triad existence, LookupState |
| ERS-EPIC-03 ERE Contract Client | `.claude/memory/epics/ers-epic-03-ere-contract-client/EPIC.md` | Redis adapter for EPIC-05 |

---
<!-- implementation-log -->
---

# Part 2 — Implementation Log

<!-- Written and updated by the implementer during Phase 3. -->

---

## Implementation Log

### 2026-03-23 — Implementation started

**Task corrections applied (pre-implementation):**
- Layer renamed from `models/` → `domain/` (project convention).
- `motor` dependency removed. Using `pymongo.asynchronous` via `MongoClientManager` + `BaseMongoRepository` from commons.
- `DecisionStoreConfig` uses `@env_property` decorator (not Pydantic `env_prefix`).
- `ResolutionDecisionRecord` eliminated — `erspec.Decision` is used directly (identical fields, different names).
- `MongoDecisionStoreRepository` extends `MongoDecisionRepository` from `ers.commons.adapters.decision_repository` — parallel sibling to `MongoDecisionCurationRepository`, both on the `decisions` collection.
- OTel tracing via `@trace_function` on module-level public functions (not class methods).
- Unit test mocking: `create_autospec(MongoDecisionStoreRepository)` (not motor mocks).
- `PaginationCursor`/`DecisionPage` replaced by `CursorPage[Decision]` from commons (reuse existing).
- `derive_provisional_cluster_id()` reuses `SHA256ContentHasher` from commons.

---

## Clarity Gate Assessment

**Document type:** Implementation | **Date:** 2026-03-12

### 13-Item Checklist

#### Foundation Checks
- [x] **Actionable** -- Concrete classes, methods, MongoDB operations, SHA256 algorithm, JSON examples, Mermaid flow.
- [x] **Current** -- Reflects developer answers from 2026-03-12 Q&A and architecture source documents.
- [x] **Single Source** -- er-spec by pointer (Section 4.1); local models defined once (Section 4.2).
- [x] **Decision, Not Wish** -- All decided: timestamp staleness, findOneAndReplace, no LookupState, SHA256 in adapter, opaque cursor, top-5, page 250.
- [x] **Prompt-Ready** -- Every section directly usable by implementer with concrete interfaces and field names.
- [x] **No Future State** -- No "might", "eventually", "ideally". EPIC-05/06/07 explicitly deferred.
- [x] **No Fluff** -- Pure specification.

#### Document Architecture Checks
- [x] **Type Identified** -- Implementation (stated after Part 1 heading).
- [x] **Anti-patterns Placed** -- Section 9, 10 entries (exceeds minimum of 5).
- [x] **Test Cases Placed** -- Section 8, 21 unit tests + 6 integration tests.
- [x] **Error Handling Placed** -- Section 6, 6 error types with layer, detection, response, log level.
- [x] **Deep Links Present** -- Section 14, 8 references with file paths and section identifiers.
- [x] **No Duplicates** -- er-spec by pointer; config defined once.

### Scoring

| Criterion | Weight | Score | Rationale |
|-----------|--------|-------|-----------|
| Actionability | 25% | 10 | Concrete interfaces, Mermaid flow, MongoDB operations, JSON examples |
| Specificity | 20% | 10 | SHA256 algorithm, findOneAndReplace semantics, timestamp rules, page sizes, candidate caps |
| Consistency | 15% | 10 | Single source for config; er-spec by pointer; no duplication |
| Structure | 15% | 10 | Tables throughout; numbered behavioural spec; clear task breakdown |
| Disambiguation | 15% | 9 | 10 anti-patterns; 6 errors; edge cases per test. Minor: exact MongoDB filter syntax left to implementer |
| Reference Clarity | 10% | 10 | 8 deep links with file paths and section identifiers |

**Score: 9.85/10** -- Weighted: (10*0.25 + 10*0.20 + 10*0.15 + 10*0.15 + 9*0.15 + 10*0.10) = 9.85. Rounded to **9.8/10** -- PASS. Ready for implementation.
