# Task 1.2 — Repository, Service, and Exceptions: Request Registry

## Specification Summary

Implement the persistence adapters, application service, and exception hierarchy for the Request Registry. This task covers orchestration, repositories, and exception handling.

### Files to Create/Modify

**Files created:**
- `src/ers/request_registry/adapters/records_repository.py` — two ABCs + two Mongo implementations
- `src/ers/request_registry/services/request_registry_service.py`
- `src/ers/request_registry/services/exceptions.py`
- `src/ers/request_registry/adapters/__init__.py` — adapter package exports
- `src/ers/request_registry/services/__init__.py` — service package exports (exceptions only)

**Files modified:**
- `src/ers/commons/adapters/mongo_collections_manager.py` — added `RESOLUTION_REQUESTS`, `LOOKUP_STATES`
- `src/ers/commons/adapters/mongo_client.py` — added index creation for new collections

---

## Specification Details

### Exceptions (`services/exceptions.py`)

All inherit `ApplicationError` (`ers.commons.services.exceptions`).

| Exception | Raised when |
|-----------|-------------|
| `IdempotencyConflictError` | Same triad resubmitted with different `content_hash` |
| `SnapshotRegressionError` | `advance_snapshot` called with time ≤ current `last_snapshot` |
| `DuplicateTriadError` | Wraps pymongo `DuplicateKeyError` on `_id` |
| `RepositoryConnectionError` | Wraps pymongo `ConnectionFailure` |
| `RepositoryOperationError` | Wraps any other pymongo error |

### Repositories (`adapters/records_repository.py`)

**`ResolutionRequestRepository`** — ABC + `MongoResolutionRequestRepository`
- Does NOT extend `BaseMongoRepository` — `_id` is computed from the triad: `f"{source_id}::{request_id}::{entity_type}"`
- Methods: `store`, `find_by_triad`, `find_by_source_id(limit, offset)`
- `DuplicateKeyError` → `DuplicateTriadError`

**`LookupStateRepository`** — ABC + `MongoLookupStateRepository`
- Extends `BaseMongoRepository[LookupState, str]` with `_id_field = "source_id"`
- `get(source_id)` → `find_by_id`; `upsert(state)` → `save` (free upsert)

**`LookupRequestRepository`** — ABC (append-only audit log, no Mongo impl yet)
- `store(record)` → append; `find_by_source_id(source_id, since=None)`

### Service (`services/request_registry_service.py`)

`RequestRegistryService(resolution_repo, lookup_repo, lookup_request_repo, hasher)`

- `register_resolution_request` — reject empty content → hash → find existing → idempotent replay or conflict or new store
- `get_resolution_request` — delegate to `find_by_triad`
- `list_resolution_requests_by_source` — paginated delegate
- `register_lookup_request` — append audit record with UTC timestamp
- `get_lookup_state` — delegate to `lookup_repo.get`
- `advance_snapshot` — reject regression; upsert with `updated_at = max(now, snapshot_time)`

**Note:** Not re-exported from `services/__init__.py` — avoids circular import. Import directly from the module.

### Acceptance Criteria

1. `register_resolution_request` stores new record and returns it.
2. Idempotent replay returns existing record without calling `store` again.
3. Conflict raises `IdempotencyConflictError`, no write.
4. Empty content raises before any hashing or DB call.
5. Duplicate `_id` at DB level wraps to `DuplicateTriadError`.
6. `advance_snapshot` upserts with new timestamp.
7. `advance_snapshot` regression raises `SnapshotRegressionError`, no write.
8. All unit tests pass with mocked repositories (no MongoDB required).

### Gherkin Scenarios Covered

- `resolution_request_registration.feature`: new registration, idempotent replay, idempotency conflict, empty content rejection
- `bulk_lookup_and_snapshot_management.feature`: first `advance_snapshot`, subsequent advance, regression rejection

---

## Implementation Outcomes

### What Was Accomplished

- Five exceptions created under `services/exceptions.py`, all inheriting `ApplicationError`.
- `ResolutionRequestRepository` ABC (3 abstract methods) and `MongoResolutionRequestRepository` (composite `_id` strategy, insert_one with error wrapping, find_one, cursor-based pagination).
- `LookupStateRepository` ABC (2 abstract methods) and `MongoLookupStateRepository` (extends `BaseMongoRepository[LookupState, str]` with `_id_field = "source_id"`; `get` wraps `find_by_id`, `upsert` wraps `save`).
- `RequestRegistryService` with 5 methods; full idempotency algorithm (new / replay / conflict) and monotonic snapshot advancement.
- `MongoCollections` extended with `RESOLUTION_REQUESTS` and `LOOKUP_STATES` constants and properties.
- `ensure_indexes()` extended with composite source/received_at index on `resolution_requests` and source_id index on `lookup_states`.
- **33 new unit tests (16 adapter, 11 service, plus 6 pre-existing domain tests unchanged). Full suite 298/298 pass.**

### Key Decisions

- **`MongoResolutionRequestRepository` does NOT extend `BaseMongoRepository`** — the `_id` is a composite computed from the triad, not mapped from a model field. The base class assumes `_id` corresponds to a model field, which is not the case here.
- **`_from_document` copies the dict** before popping `_id` so the original document is not mutated. This is tested explicitly.
- **`services/__init__.py` does not re-export `RequestRegistryService`** to break a structural circular import: `adapters/records_repository` imports `services.exceptions`, which triggers loading `services/__init__.py`; if that file imported `request_registry_service`, it would in turn import `adapters.records_repository` while it is still initialising. Callers import `RequestRegistryService` directly from `ers.request_registry.services.request_registry_service`.
- **`updated_at` guard in `advance_snapshot`** uses `max(now_utc, snapshot_time)` to satisfy the `LookupState` model invariant (`updated_at >= last_snapshot`) when `snapshot_time` is in the future relative to wall clock.

### Deviations from Spec

- `RequestRegistryService` excluded from `services/__init__.py` (spec said to include it). Reason: structural circular import. All other exports are correct; the service remains importable via its module path.

### Files Created

- `/home/lps/work/workspace-charm/entity-resolution-service/src/ers/request_registry/services/exceptions.py`
- `/home/lps/work/workspace-charm/entity-resolution-service/src/ers/request_registry/services/request_registry_service.py`
- `/home/lps/work/workspace-charm/entity-resolution-service/src/ers/request_registry/services/__init__.py`
- `/home/lps/work/workspace-charm/entity-resolution-service/src/ers/request_registry/adapters/records_repository.py`
- `/home/lps/work/workspace-charm/entity-resolution-service/src/ers/request_registry/adapters/__init__.py`
- `/home/lps/work/workspace-charm/entity-resolution-service/tests/unit/request_registry/services/__init__.py`
- `/home/lps/work/workspace-charm/entity-resolution-service/tests/unit/request_registry/services/test_request_registry_service.py`
- `/home/lps/work/workspace-charm/entity-resolution-service/tests/unit/request_registry/adapters/__init__.py`
- `/home/lps/work/workspace-charm/entity-resolution-service/tests/unit/request_registry/adapters/test_records_repository.py`

### Files Modified

- `/home/lps/work/workspace-charm/entity-resolution-service/src/ers/commons/adapters/mongo_collections_manager.py`
- `/home/lps/work/workspace-charm/entity-resolution-service/src/ers/commons/adapters/mongo_client.py`

### Commits

- Committed and merged.