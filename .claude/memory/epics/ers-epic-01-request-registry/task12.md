# Task 1.2 — Repository, Service, and Exceptions: Request Registry

**Files created:**
- `src/ers/request_registry/adapters/records_repository.py` — two ABCs + two Mongo implementations
- `src/ers/request_registry/services/request_registry_service.py`
- `src/ers/request_registry/services/exceptions.py`

**Files modified:**
- `src/ers/commons/adapters/mongo_collections_manager.py` — added `RESOLUTION_REQUESTS`, `LOOKUP_STATES`
- `src/ers/commons/adapters/mongo_client.py` — added index creation for new collections

---

## Exceptions (`services/exceptions.py`)

All inherit `ApplicationError` (`ers.commons.services.exceptions`).

| Exception | Raised when |
|-----------|-------------|
| `IdempotencyConflictError` | Same triad resubmitted with different `content_hash` |
| `SnapshotRegressionError` | `advance_snapshot` called with time ≤ current `last_snapshot` |
| `DuplicateTriadError` | Wraps pymongo `DuplicateKeyError` on `_id` |
| `RepositoryConnectionError` | Wraps pymongo `ConnectionFailure` |
| `RepositoryOperationError` | Wraps any other pymongo error |

---

## Repositories (`adapters/records_repository.py`)

**`ResolutionRequestRepository`** — ABC + `MongoResolutionRequestRepository`
- Does NOT extend `BaseMongoRepository` — `_id` is computed from the triad: `f"{source_id}::{request_id}::{entity_type}"`
- Methods: `store`, `find_by_triad`, `find_by_source_id(limit, offset)`
- `DuplicateKeyError` → `DuplicateTriadError`

**`LookupStateRepository`** — ABC + `MongoLookupStateRepository`
- Extends `BaseMongoRepository[LookupState, str]` with `_id_field = "source_id"`
- `get(source_id)` → `find_by_id`; `upsert(state)` → `save` (free upsert)

**`LookupRequestRepository`** — ABC (append-only audit log, no Mongo impl yet)
- `store(record)` → append; `find_by_source_id(source_id, since=None)`

---

## Service (`services/request_registry_service.py`)

`RequestRegistryService(resolution_repo, lookup_repo, lookup_request_repo, hasher)`

- `register_resolution_request` — reject empty content → hash → find existing → idempotent replay or conflict or new store
- `get_resolution_request` — delegate to `find_by_triad`
- `list_resolution_requests_by_source` — paginated delegate
- `register_lookup_request` — append audit record with UTC timestamp
- `get_lookup_state` — delegate to `lookup_repo.get`
- `advance_snapshot` — reject regression; upsert with `updated_at = max(now, snapshot_time)`

**Note:** Not re-exported from `services/__init__.py` — avoids circular import (`adapters → services.exceptions → services.__init__ → request_registry_service → adapters`). Import directly from the module.

---

## Acceptance criteria

1. `register_resolution_request` stores new record and returns it.
2. Idempotent replay returns existing record without calling `store` again.
3. Conflict raises `IdempotencyConflictError`, no write.
4. Empty content raises before any hashing or DB call.
5. Duplicate `_id` at DB level wraps to `DuplicateTriadError`.
6. `advance_snapshot` upserts with new timestamp.
7. `advance_snapshot` regression raises `SnapshotRegressionError`, no write.
8. All unit tests pass with mocked repositories (no MongoDB required).
