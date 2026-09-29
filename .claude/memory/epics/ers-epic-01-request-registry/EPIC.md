# Epic: ERS-EPIC-01 — Request Registry

## Status
- Phase: Implementation complete (Tasks 1.1, 1.2, 1.3, 14). Integration tests pending.
- Last updated: 2026-03-21

## Metadata
| Field | Value |
|-------|-------|
| Epic ID | ERS-EPIC-01 |
| Component | #1 — Request Registry |
| Spines | A (intake), B (engine outcomes), C (bulk sync), D (curation) |
| Dependencies | `er-spec` library (shared domain models) |
| Downstream dependents | All other EPICs (Decision Store, Resolution Coordinator, Bulk Lookup, Curation, Statistics) |

---
# Part 1 — Specification

## 1. Business Context

The Request Registry is the foundational persistence layer of the Entity Resolution System (ERS). It implements the **System of Request Records** described in the conceptual information architecture (Section 9.1-9.2 of the ERS Architecture).

Its purpose is threefold:

1. **Immutable intake record** — Store every accepted Entity Mention and its correlation triad `(sourceId, requestId, entityType)` as an append-only, immutable record. Once accepted, a mention is never modified, merged, versioned, or deleted.
2. **Idempotency enforcement** — Use the triad as the sole uniqueness constraint. Replay of an identical triad returns the existing record. Reuse of a triad with different payload content is rejected as an idempotency conflict.
3. **Snapshot state tracking** — Maintain per-sourceId snapshot marker records (`LookupRequestRecord`) that track when the last bulk lookup was successfully produced, enabling delta exposure semantics for UC-W3 (refreshBulk).

**Implementation Implication:** This component is the first to be built. Every other ERS component depends on the Request Registry for intake validation, triad-based correlation, and snapshot state management.

---

## 2. Scope

### In scope

- Pydantic models for: `ResolutionRequestRecord`, `LookupRequestRecord`
- MongoDB repository (adapters) for persisting and querying these models
- Service layer for storing, retrieving request records and snapshot state management
- Idempotency enforcement at the service level (triad uniqueness check)
- RDF parsing of entity mention content at registration time — result stored in `parsed_representation`
- Import and reuse of `er-spec` domain models (`EntityMentionIdentifier`, `EntityMention`, `LookupState`)
- OpenTelemetry instrumentation via module-level public functions

### Out of scope

- Bulk request decomposition (EPIC-06: Resolution Coordinator)
- Resolution logic, provisional identifier issuance (EPIC-06)
- Decision Store persistence (EPIC-02 or dedicated Decision Store EPIC)
- REST API / entrypoints (separate EPIC)
- User Action Log (Curation EPIC)
- Authentication / authorisation
- OTel metrics (counters, histograms) — traces only

---

## 3. Glossary

| Term | Definition |
|------|-----------|
| **Triad** | The composite key `(source_id, request_id, entity_type)` from `EntityMentionIdentifier`. Sole correlation and uniqueness key for Entity Mentions in ERS. |
| **Resolution Request Record** | An ERS-local record extending `EntityMention` with intake metadata (`content_hash`, `received_at`, `parsed_representation`). Immutable once stored. |
| **Lookup Request Record** | Per-sourceId snapshot marker tracking when the last bulk lookup was successfully produced. Advances monotonically. |
| **Snapshot marker** | The `last_snapshot` timestamp in `LookupRequestRecord`. Marks the last point in time for which bulk results were produced for a source. Must advance strictly forward. |
| **Idempotency conflict** | Reuse of an existing triad with different payload content. Rejected with an explicit error. |
| **Idempotent replay** | Reuse of an existing triad with identical payload content. Returns the existing record without side effects. |
| **er-spec** | External shared library providing domain models (`EntityMention`, `EntityMentionIdentifier`, `LookupState`, etc.) used across ERS and ERE. |

---

## 4. Domain Model

### 4.1 Models imported from er-spec

These models are imported, not redefined. The er-spec library is the single source of truth.

| Model | Key fields | Notes |
|-------|-----------|-------|
| `EntityMentionIdentifier` | `source_id: str`, `request_id: str`, `entity_type: str` | The triad. Immutable value object. |
| `EntityMention` | `identifiedBy: EntityMentionIdentifier`, `content: str`, `content_type: str`, `parsed_representation: Optional[str]`, `context: Optional[str]` | Immutable intake artefact. `parsed_representation` carries the JSON-serialised RDF parse result. |
| `LookupState` | `source_id: str`, `last_snapshot: datetime` | Base model for snapshot state. Extended by `LookupRequestRecord`. |

### 4.2 Models defined in this EPIC

#### ResolutionRequestRecord

```python
class ResolutionRequestRecord(FrozenDTO, EntityMention):
    """Immutable intake record for a single entity mention resolution request."""
    content_hash: str      # SHA-256 hex digest of content (64 chars)
    received_at: datetime  # UTC timestamp of first acceptance (timezone-aware)
```

- Extends `EntityMention` — all erspec fields are inlined (`identifiedBy`, `content`, `content_type`, `parsed_representation`, `context`).
- `parsed_representation` is populated at registration time by the RDF parser; stored as a JSON string.
- `content_hash` enables idempotency conflict detection: same triad + different hash = conflict.
- `received_at` is set once at creation time, never updated.
- Triad fields (`source_id`, `request_id`, `entity_type`) must all be non-empty (validated at model construction).

#### LookupRequestRecord

```python
class LookupRequestRecord(FrozenDTO, LookupState):
    """Per-source snapshot marker for bulk delta exposure.

    Tracks the last point in time for which bulk results were successfully
    produced for a source. Advances monotonically — regression is rejected
    by the service layer.
    """
    updated_at: datetime  # wall-clock UTC time of last state update
```

- Extends erspec `LookupState` (`source_id`, `last_snapshot`) with `updated_at`.
- `last_snapshot` maps to `lastNotificationDate` in the architecture.
- Advanced only after a bulk refresh response is successfully produced.
- `updated_at >= last_snapshot` is enforced by a model validator.

---

## 5. Adapter Specification (MongoDB Repository)

### 5.1 Collections

| Collection | Document root model | Unique index | Additional indexes |
|-----------|-------------------|-------------|-------------------|
| `resolution_requests` | `ResolutionRequestRecord` | `(identifiedBy.source_id, identifiedBy.request_id, identifiedBy.entity_type)` compound — computed as `_id` | `received_at` (ascending), `identifiedBy.source_id` (ascending) |
| `lookup_states` | `LookupRequestRecord` | `source_id` unique (used as `_id`) | None |

### 5.2 Repository classes

Two separate concrete classes (no shared ABC — only one concrete implementation exists):

```python
class MongoResolutionRequestRepository(BaseMongoRepository[ResolutionRequestRecord, str]):
    async def store(record: ResolutionRequestRecord) -> ResolutionRequestRecord
    async def find_by_triad(identifier: EntityMentionIdentifier) -> ResolutionRequestRecord | None
    async def find_by_source_id(source_id: str, limit: int, offset: int) -> list[ResolutionRequestRecord]

class MongoLookupStateRepository(BaseMongoRepository[LookupRequestRecord, str]):
    async def get(source_id: str) -> LookupRequestRecord | None
    async def upsert(state: LookupRequestRecord) -> LookupRequestRecord
```

Note: `MongoResolutionRequestRepository` does not use `BaseMongoRepository._id_field` — the `_id` is computed from the triad as `source_id::request_id::entity_type`.

### 5.3 Custom Exceptions (adapter layer)

| Exception | Raised when |
|-----------|------------|
| `DuplicateTriadError` | Attempting to store a `ResolutionRequestRecord` with a triad that already exists. Wraps MongoDB duplicate key error. |
| `RepositoryConnectionError` | MongoDB connection failure. |
| `RepositoryOperationError` | Generic persistence operation failure (timeouts, write concern errors, etc.). |

---

## 6. Service Specification

### 6.1 Service class

```python
class RequestRegistryService:
    def __init__(
        self,
        resolution_repo: MongoResolutionRequestRepository,
        lookup_repo: MongoLookupStateRepository,
        hasher: ContentHasher,
        rdf_config: RDFMappingConfig,
    ) -> None: ...

    async def register_resolution_request(entity_mention: EntityMention) -> ResolutionRequestRecord
    async def get_resolution_request(identifier: EntityMentionIdentifier) -> ResolutionRequestRecord | None
    async def get_lookup_state(source_id: str) -> LookupRequestRecord | None
    async def advance_snapshot(source_id: str, snapshot_time: datetime) -> LookupRequestRecord
```

### 6.2 Registration algorithm

```
1. Reject empty content → ValueError.
2. Compute content_hash (SHA-256 of entity_mention.content).
3. find_by_triad(identifier):
   a. Exists + same hash → return existing (idempotent replay).
   b. Exists + different hash → raise IdempotencyConflictError.
   c. Not exists → parse RDF content → store record with parsed_representation → return.
```

RDF parsing exceptions (`ContentTooLargeError`, `UnsupportedEntityTypeError`, `MalformedRDFError`, etc.) propagate to the caller unchanged.

### 6.3 Public API functions (module-level)

Per project OTel convention, `@trace_function` is placed on module-level public functions, not class methods:

```python
@trace_function(span_name="request_registry.register_resolution")
async def register_resolution_request(entity_mention, service) -> ResolutionRequestRecord

@trace_function(span_name="request_registry.get_resolution")
async def get_resolution_request(identifier, service) -> ResolutionRequestRecord | None

@trace_function(span_name="request_registry.get_lookup_state")
async def get_lookup_state(source_id, service) -> LookupRequestRecord | None

@trace_function(span_name="request_registry.advance_snapshot")
async def advance_snapshot(source_id, snapshot_time, service) -> LookupRequestRecord
```

### 6.4 Service Exceptions

| Exception | Raised when |
|-----------|------------|
| `IdempotencyConflictError` | Same triad submitted with different content (different `content_hash`). |
| `SnapshotRegressionError` | Attempting to set `last_snapshot` to a time earlier than or equal to the current value. |

### 6.5 Observability

- OTel spans emitted via module-level public functions (not class methods).
- Span attributes auto-extracted from `ResolutionRequestRecord` via extractor registry (`request_registry/adapters/span_extractors.py`).
- Extractor imported in app factory (`create_app()`), not at module level.
- Metrics (counters, histograms): out of scope for this EPIC.

---

## 7. Anti-Patterns (DO NOT)

| Don't | Do Instead | Why |
|-------|-----------|-----|
| Mutate a `ResolutionRequestRecord` after storage | Treat records as immutable; create new derived artefacts if needed | Immutability is a strict architectural invariant (Section 9.2). |
| Use a surrogate key as the primary correlation key | Use the triad `(source_id, request_id, entity_type)` as the sole key | Architecture mandates the triad. Surrogates create shadow identity. |
| Implement idempotency checks inside the adapter/repository | Implement idempotency logic in the service layer; adapter only enforces the unique index | SRP. |
| Put OpenTelemetry on class methods | Place `@trace_function` on module-level public functions (the API boundary) | Project OTel convention — class methods are implementation details. |
| Advance the snapshot marker on request receipt | Advance `last_snapshot` only after a bulk refresh response is successfully produced | Premature advancement breaks delta exposure guarantees (Section 9.2, UC-W3). |
| Compare entity mention content as raw strings for idempotency | Use SHA-256 content hash for comparison | Hashing is deterministic and encoding-safe. |
| Import from `services` or `entrypoints` into `models` or `adapters` | Respect dependency direction: `entrypoints` -> `services` -> `models`, `adapters` -> `models` | Layered architecture invariant. |

---

## 8. Test Case Specifications

### Unit Tests

| Test ID | Component | Input | Expected Output |
|---------|-----------|-------|-----------------|
| TC-001 | `ResolutionRequestRecord` model | Valid `EntityMention` + `content_hash` + `received_at` | Frozen model; triad fields non-empty enforced |
| TC-002 | `LookupRequestRecord` model | Valid `source_id`, `last_snapshot`, `updated_at` | Frozen model; `updated_at >= last_snapshot` enforced |
| TC-003 | Service: `register_resolution_request` (new) | New `EntityMention` with unique triad | Record stored with SHA-256 hash, `parsed_representation` set, UTC `received_at` |
| TC-004 | Service: `register_resolution_request` (replay) | Same `EntityMention` twice | Returns existing record; `store` not called |
| TC-005 | Service: `register_resolution_request` (conflict) | Same triad, different content | Raises `IdempotencyConflictError`; `store` not called |
| TC-006 | Service: `register_resolution_request` (empty) | `content=""` | Raises `ValueError` before any repo call |
| TC-007 | Service: `advance_snapshot` (new source) | No existing state, `snapshot_time` T | New `LookupRequestRecord` with `last_snapshot=T` |
| TC-008 | Service: `advance_snapshot` (existing source) | Existing `last_snapshot=T1`, advance to `T2 > T1` | `last_snapshot` updated to `T2` |
| TC-009 | Service: `advance_snapshot` (regression) | `snapshot_time <= current last_snapshot` | Raises `SnapshotRegressionError`; `upsert` not called |
| TC-010 | Repository: `store` (duplicate triad) | Record with existing triad | Raises `DuplicateTriadError` |
| TC-011 | Repository: `find_by_triad` (not found) | Non-existent triad | Returns `None` |
| TC-012 | Content hash computation | Known content string | Deterministic SHA-256 hex digest |

### Integration Tests

| Test ID | Flow | Verification |
|---------|------|--------------|
| IT-001 | Store and retrieve resolution request | Store record, retrieve by triad, verify all fields match |
| IT-002 | Idempotency enforcement end-to-end | Same triad+content → replay OK; same triad+different content → conflict error |
| IT-003 | Snapshot state lifecycle | Advance marker, verify `last_snapshot` updated; attempt regression → error |
| IT-004 | Unique index enforcement | Insert duplicate triad at MongoDB level → `DuplicateTriadError` |
| IT-005 | Concurrent request registration | 10 identical requests concurrently → exactly 1 stored, 9 return existing |

---

## 9. Error Handling Matrix

| Error Type | Detection | Response | Logging Level |
|------------|-----------|----------|---------------|
| Idempotency conflict | SHA-256 hash mismatch on existing triad | Raise `IdempotencyConflictError` | WARN (includes triad, excludes content) |
| Duplicate triad (MongoDB) | `DuplicateKeyError` from pymongo | Adapter wraps as `DuplicateTriadError` | DEBUG |
| MongoDB connection failure | `ConnectionFailure` from pymongo | Adapter wraps as `RepositoryConnectionError` | ERROR |
| MongoDB operation timeout | `ServerSelectionTimeoutError` | Adapter wraps as `RepositoryOperationError` | ERROR |
| Snapshot regression | `snapshot_time <= current last_snapshot` | Raise `SnapshotRegressionError` | WARN |
| Empty content | `entity_mention.content` is empty string | Raise `ValueError` before any repo call | Not logged |
| RDF parse failure | Parser raises domain exception | Propagate unchanged to caller | Logged by parser |

---

## 10. Task Breakdown

### Task 1.1: Define domain models ✅
- `ResolutionRequestRecord`, `LookupRequestRecord` created under `domain/records.py`.

### Task 1.2: Repository, Service, and Exceptions ✅
- `MongoResolutionRequestRepository`, `MongoLookupStateRepository` in `adapters/records_repository.py`.
- `RequestRegistryService` in `services/request_registry_service.py`.
- Five exceptions in `services/exceptions.py`.

### Task 1.3: Wire BDD feature files ✅
- BDD step definitions wired with real service calls.

### Task 14: Public API functions and RDF integration ✅
- Module-level public functions with `@trace_function`.
- RDF parsing integrated into `register_resolution_request`.
- `list_resolution_requests_by_source` and `register_lookup_request` removed (no feature file coverage).
- "watermark" eliminated from all source code, specs, and feature files.
- Span extractor wired in `ers_rest_api` app factory.
- Unit and BDD tests updated: `rdf_config` + `mock_parse_entity_mention` fixtures added; all 327 unit + 200 feature tests green.

### Task 5: Integration tests ⬜
- Integration tests against real MongoDB (testcontainers or docker-compose).
- Coverage: IT-001 through IT-005.

## Roadmap

- [x] Task 1.1: Define domain models — [outcomes](task11-domain-models.md)
- [x] Task 1.2: Repository, Service, and Exceptions — [outcomes](task12-repository-service-exceptions.md)
- [x] Task 1.3: Wire BDD feature files — completed 2026-03-20
- [x] Task 14: Public API functions and RDF parsing integration — [outcomes](task14.md)
- [ ] Task 5: Write integration tests

---

## 11. Gherkin Feature Outline

### Feature: Resolution Request Registration

| Scenario | Description |
|----------|------------|
| Register a new resolution request | Given a valid EntityMention with a unique triad, when registered, a ResolutionRequestRecord is stored with correct content_hash, parsed_representation, and received_at. |
| Idempotent replay of identical request | Given an already-registered triad with identical content, when resubmitted, the existing record is returned without creating a duplicate. |
| Reject idempotency conflict | Given an already-registered triad, when a request with the same triad but different content is submitted, an IdempotencyConflictError is raised. |
| Reject empty content | Given an EntityMention with empty content, when registered, a ValueError is raised and no record is created. |

### Feature: Snapshot State Management

| Scenario | Description |
|----------|------------|
| Advance snapshot for new source | Given no existing state for a source_id, when advance_snapshot is called, a new LookupRequestRecord is created with the given snapshot_time. |
| Advance snapshot for existing source | Given existing state with last_snapshot T1, when advance_snapshot is called with T2 > T1, last_snapshot is updated to T2. |
| Reject snapshot regression | Given existing state with last_snapshot T1, when advance_snapshot is called with T2 <= T1, a SnapshotRegressionError is raised. |
| Retrieve snapshot state for known source | Given a source with existing state, when get_lookup_state is called, the LookupRequestRecord is returned. |
| Retrieve snapshot state for unknown source | Given no state for a source, when get_lookup_state is called, None is returned. |

---

## 12. Risks and Assumptions

### Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| er-spec model changes break ERS models | HIGH — all EPICs depend on er-spec | Pin er-spec version; integration test on upgrade |
| MongoDB connection pool exhaustion under load | MEDIUM | Configure pool size; circuit breaker in adapter |
| Race condition on concurrent identical requests | LOW | MongoDB unique index as last-line defence; service catches `DuplicateTriadError` and retries idempotency check |
| RDF parser rejects content that passes idempotency check | MEDIUM | Parser exceptions propagate cleanly; no partial record stored |

### Assumptions

1. The `er-spec` library is available as a Python package installable via pip/poetry.
2. MongoDB is available as the persistence backend (version >= 6.0).
3. The `motor` async driver is used for MongoDB access.
4. All timestamps are UTC and stored as ISO 8601 in MongoDB.
5. The `content_hash` is computed from `entity_mention.content` only.
6. Idempotency logic lives exclusively in the service layer; the adapter enforces the unique index as a safety net.
7. RDF parsing config (`RDFMappingConfig`) is loaded once and injected into the service constructor.

---

## 13. Architectural Constraints

1. **Immutability of intake records** — Once a `ResolutionRequestRecord` is stored, it is never modified, merged, versioned, or deleted. (Section 9.2)
2. **Triad as sole correlation key** — No surrogate identifiers replace `(source_id, request_id, entity_type)`. (Section 9.2)
3. **Idempotency via triad** — Reuse of an existing triad with different payload is rejected. Identical replay returns existing record. (Spine A, ADR-C1N)
4. **At-least-once tolerance** — The system must handle duplicate submissions without creating inconsistent state. (Spine A, ERS-ERE Contract)
5. **Delta rule** — `lastNotificationDate < lastUpdateDate` drives bulk exposure. Snapshot marker must only advance on successful response production. (Section 9.2, UC-W3)
6. **Layered architecture** — `entrypoints` -> `services` -> `models`, `adapters` -> `models`. No reverse imports. (Cosmic Python / project conventions)
7. **Observability at public function boundary** — `@trace_function` on module-level public functions only, not class methods. (Project OTel convention)
8. **er-spec as single source of truth** — Domain models from er-spec are imported, not redefined. ERS-local models extend them. (Architecture Section 9)

---

## 14. Dependencies

| Dependency | Type | Purpose |
|-----------|------|---------|
| `er-spec` | Python package (external) | Shared domain models |
| `pydantic` | Python package | Model definitions |
| `motor` | Python package | Async MongoDB driver |
| `pymongo` | Python package (transitive) | MongoDB operations and exceptions |
| `opentelemetry-api` + `opentelemetry-sdk` | Python packages | Tracing instrumentation |
| MongoDB | Infrastructure | Persistence backend (>= 6.0) |

---

## 15. References

| Topic | Location | Section |
|-------|----------|---------|
| System of Request Records | `docs/modules/ROOT/pages/ERSArchitecture/conceptual-model.adoc` | Section 9.1-9.2 |
| Spine A: Resolution intake | `docs/modules/ROOT/pages/ERSArchitecture/spine-a.adoc` | Section 8.2 |
| Delta exposure state | `docs/modules/ROOT/pages/ERSArchitecture/conceptual-model.adoc` | Section 9.1 |
| UC-W1 Resolve Entity Mention | `docs/modules/ROOT/pages/ERSArchitecture/core-capabilities.adoc` | Section 7.1 |
| UC-W3 refreshBulk | `docs/modules/ROOT/pages/ERSArchitecture/core-capabilities.adoc` | Section 7.3 |
| ERS-ERE Contract: EntityMention | `docs/modules/ROOT/pages/ERS-ERE-Contarct/interface.adoc` | Entity Mention sections |
| Idempotency ADRs | `docs/modules/ROOT/pages/AnnexeC-ADRs/adrc1.adoc` | ADR-C1N |

---
<!-- implementation-log -->
---

# Part 2 — Implementation Log

### 2026-03-21 — Task 14: Public API functions and RDF parsing integration

- **Outcome:** Module-level public async functions added to `request_registry_service.py` for all four service operations, each decorated with `@trace_function`. RDF parsing integrated into `register_resolution_request` — result stored in `parsed_representation` (JSON string). `list_resolution_requests_by_source` and `register_lookup_request` removed (no feature file coverage; latter is covered by `advance_snapshot`). `rdf_config: RDFMappingConfig` added as required constructor argument. `ers.request_registry.adapters.span_extractors` wired in `ers_rest_api` app factory. "watermark" eliminated from all source files, tests, specs, and feature files. Unit and BDD tests updated with `rdf_config` fixture and `mock_parse_entity_mention` patch (new-triad path only); 327 unit + 200 feature tests green.
- **Decisions:** `parsed_representation` not added as a new field — it already exists on erspec's `EntityMention` as `Optional[str]`. RDF parsing moved in-scope from EPIC-02: parsing and registration are atomic — storing without parsing would leave records in an unusable state. Public functions take `service` as the last parameter (data first, service last — consistent with `parse_entity_mention(entity_mention, config)`). `mock_parse_entity_mention` patches at the service module import, not the source module, to correctly intercept the call.
- **Deviations:** RDF parsing was explicitly out of scope in original EPIC Section 2. Scope change deliberate and approved.

### 2026-03-20 — Task 1.3: BDD feature file wiring

- **Outcome:** All TODO stubs in BDD step files replaced with real service calls. All scenarios pass.
- **Decisions:** Steps import `RequestRegistryService` directly from module (not from `services/__init__.py`) to avoid circular import.
- **Deviations:** None relative to the Gherkin scenarios.

### 2026-03-20 — Task 1.2: Repository, Service, and Exceptions

- **Outcome:** Five exceptions created. Two Mongo repository classes and `RequestRegistryService` implemented. `ensure_indexes()` extended. 33 new unit tests; full suite 298/298 pass.
- **Decisions:** `MongoResolutionRequestRepository` does not use `_id_field` — `_id` is computed from the triad. `MongoLookupStateRepository` uses `_id_field = "source_id"`. `RequestRegistryService` not re-exported from `services/__init__.py` (circular import). `updated_at` uses `max(now, snapshot_time)` to satisfy `updated_at >= last_snapshot` invariant.
- **Deviations:** `RequestRegistryService` not in `services/__init__.py`.

### 2026-03-19 — Task 1.1: Domain models

- **Outcome:** `ResolutionRequestRecord`, `LookupRequestRecord` created as frozen Pydantic models. `SHA256ContentHasher` added. 35 new unit tests; full suite 276/276 pass.
- **Decisions:** `ResolutionRequestRecord` extends `EntityMention` directly (fields inlined). `LookupRequestRecord` extends erspec `LookupState`. No `JSONRepresentation` wrapper — `parsed_representation: Optional[str]` on erspec `EntityMention` serves this purpose.
- **Deviations:** `LookupRequestType` enum not implemented. `JSONRepresentation` not implemented. `LookupState` not defined locally — erspec model used directly.

### 2026-03-16 — Gherkin features and step scaffolding

- **Outcome:** 2 feature files created; step definitions scaffolded with TODO placeholders.
- **Deviations:** None.
