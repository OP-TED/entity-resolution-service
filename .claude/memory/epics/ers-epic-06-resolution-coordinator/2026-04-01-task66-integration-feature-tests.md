---
date: 2026-04-01
task: T6.6 — Integration + Feature Tests
branch: feature/ERS1-145-task65
status: complete
---

# T6.6 Outcome: Integration + Feature Tests

## What was delivered

### Part A — BDD Feature Tests (4 files, 29 scenarios, all green)

All four BDD feature files were wired with real service calls and proper mocking:

- `tests/feature/resolution_coordinator/test_async_resolution_waiter.py` — 7 scenarios
- `tests/feature/resolution_coordinator/test_single_mention_resolution.py` — 9 scenarios
- `tests/feature/resolution_coordinator/test_bulk_resolution.py` — 7 scenarios
- `tests/feature/resolution_coordinator/test_bulk_lookup.py` — 6 scenarios

Key patterns used:
- `asyncio.run()` in sync `def` step functions (consistent with project BDD pattern)
- Fast config patch: `ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET=0.1`
- ERE simulation via `asyncio.create_task(_notify())` with `asyncio.sleep(0.02)` + `waiter.notify(key)`
- Identity-aware mock dispatch keyed by `(source_id, request_id)` for concurrent scenarios
- No catch-all `parsers.parse("{param}")` steps — all explicit to avoid cross-file step conflicts

### Part B — Integration Tests (9 tests, all green)

New file: `tests/integration/resolution_coordinator/test_resolution_coordinator_integration.py`

| Test | Description |
|------|-------------|
| IT-001 | Full happy path — ERE responds, canonical Decision returned and persisted |
| IT-002 | Timeout → provisional singleton issued and persisted |
| IT-003 | Redis down → provisional returned, persisted in MongoDB |
| IT-004 | Idempotent replay — existing decision returned, no new ERE publish |
| IT-005 | 5 concurrent identical requests → all return same Decision |
| IT-006 | Bulk decomposition — 3 mentions, all succeed independently |
| IT-007 | Bulk refresh delta — 3 changed since snapshot, 2 old ignored |
| IT-008 | Bulk refresh first lookup — all 4 decisions for source returned |
| IT-009 | Unknown source → SourceNotFoundException raised |

## Bug fixes surfaced by tests

### 1. Concurrent registration race (`DuplicateTriadError`)

**File:** `src/ers/resolution_coordinator/services/resolution_coordinator_service.py`

**Problem:** When 5 concurrent coroutines call `resolve_single` with the same triad, all find no existing record and attempt `insert_one`. Only 1 succeeds; the others get `DuplicateTriadError` which propagated unhandled.

**Fix:** Catch `DuplicateTriadError` after `register_resolution_request` and pass — a concurrent insert means the record already exists with the same content; proceeding to the decision check is safe.

### 2. MongoDB naive datetime deserialization (`LookupRequestRecord`)

**File:** `src/ers/request_registry/adapters/records_repository.py`

**Problem:** PyMongo returns naive UTC datetimes. `LookupRequestRecord` has a Pydantic validator that rejects naive datetimes. `BaseMongoRepository._from_document` used raw `model_validate` without UTC conversion, causing `ValidationError` on every read of lookup state.

**Fix:** Overrode `_from_document` in `MongoLookupStateRepository` to add `UTC` tzinfo to any naive `last_snapshot` / `updated_at` fields before `model_validate`.

## Test infrastructure

- `parse_entity_mention` patched in `registry_service` fixture (coordinator tests don't test RDF parsing)
- All integration tests require `@pytest.mark.integration` + live MongoDB + Redis
- Redis fixture: `RedisEREClient(config_or_client=redis_client, ...)`
- MongoDB fixture: `mongo_db` (function scope, dropped after each test)
