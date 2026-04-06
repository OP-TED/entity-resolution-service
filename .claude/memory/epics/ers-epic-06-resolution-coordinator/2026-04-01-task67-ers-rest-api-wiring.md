---
date: 2026-04-01
task: T6.7 — ERS REST API Wiring
branch: feature/ERS1-145-task64
status: complete
---

# T6.7 Outcome: ERS REST API Wiring

## What was delivered

### Part 1 — Lifespan (`app.py`)

- `AsyncResolutionWaiter` created as process-scoped singleton in `app.state.waiter`
- `RedisEREClient` created from config and stored in `app.state.redis_client`
- Separate `RedisEREClient` for the outcome listener (needs its own BRPOP connection)
- `OutcomeIntegrationService` wired with `waiter.notify` as `on_outcome_stored` callback
- `OutcomeIntegrationWorker` started on app startup, stopped on shutdown
- Proper cleanup: worker stop → Redis close → MongoDB close

### Part 2 — Dependencies (`dependencies.py`)

**Removed:**
- `get_decision_repository` — direct repository exposure to REST API
- `get_resolution_request_repository` — direct repository exposure to REST API
- All imports of `BaseDecisionRepository`, `BaseMongoDecisionRepository`, `ResolutionDecisionStoreServiceABC`

**Added (internal providers, prefixed with `_`):**
- `_get_decision_store_service(db)` → `DecisionStoreService(MongoDecisionRepository(db))`
- `_get_request_registry_service(db)` → `RequestRegistryService(...)` with RDF config
- `_get_ere_publish_service(client)` → `EREPublishService(adapter=client)`
- `_get_waiter(request)` → from `app.state.waiter`
- `_get_redis_client(request)` → from `app.state.redis_client`
- `_get_rdf_config()` — cached RDF mapping config loader
- `_get_bulk_refresh_coordinator(...)` → `BulkRefreshCoordinatorService`

**Updated (public orchestrators):**
- `get_resolution_coordinator` — now returns real `ResolutionCoordinatorService` (was `NotImplementedError`)
- `get_resolve_service` — unchanged (depends on coordinator)
- `get_lookup_service` — now depends on `ResolutionCoordinatorService` (was `ResolutionDecisionStoreServiceABC`)
- `get_refresh_bulk_service` — now depends on `BulkRefreshCoordinatorService` (was `ResolutionDecisionStoreServiceABC`)

### Part 3 — ResolveService

- `handle_resolve` now receives `Decision` from coordinator, maps to `EntityMentionResolutionResult`
- Provisional detection via `derive_provisional_cluster_id(identifier)` comparison
- `handle_bulk_resolve` now uses `coordinator.resolve_bulk()` for concurrent resolution (was sequential loop)
- `_map_decision()` and `_map_error()` helper functions for mapping
- `_is_provisional()` helper for provisional detection

### Part 4 — RefreshBulkService

- Constructor now takes `BulkRefreshCoordinatorService` (was `ResolutionDecisionStoreServiceABC`)
- `handle_refresh_bulk` delegates to `coordinator.refresh_bulk()`, maps `CursorPage[Decision]` → `RefreshBulkResponse`
- Snapshot advancement is now handled by the coordinator (was inline in the service)

### Part 5 — LookupService (Option A — coordinator gateway)

- Constructor now takes `ResolutionCoordinatorService` (was `ResolutionDecisionStoreServiceABC`)
- Uses `coordinator.lookup_by_triad(identifier)` instead of direct Decision Store access
- New `lookup_by_triad()` method added to `ResolutionCoordinatorService` — thin delegate to `DecisionStoreService.get_decision_by_triad()`

### Part 6 — Exception Handlers

New handlers added to `exception_handlers.py`:
- `ParsingFailedException` → 400 (PARSING_FAILED)
- `IdempotencyConflictError` → 422 (IDEMPOTENCY_CONFLICT)
- `SourceNotFoundException` → 404 (SOURCE_NOT_FOUND)
- `ResolutionTimeoutException` → 504 (SERVICE_TIMEOUT)

New error codes added to `ErrorCode` enum:
- `PARSING_FAILED`, `SOURCE_NOT_FOUND`, `SERVICE_TIMEOUT`

## Architecture outcome

The Resolution Coordinator is now the **sole gateway** for all REST API endpoints:

| Endpoint | Service | Gateway |
|----------|---------|---------|
| POST /resolve, /resolve-bulk | ResolveService | ResolutionCoordinatorService |
| GET /lookup, POST /lookup-bulk | LookupService | ResolutionCoordinatorService |
| POST /refresh-bulk | RefreshBulkService | BulkRefreshCoordinatorService |

No REST API code directly imports repositories, the Decision Store, or the Request Registry. The legacy `ResolutionDecisionStoreServiceABC` is no longer referenced by any production code.

## Test results

- 986 tests pass (708 unit + 278 feature), zero failures
- All existing endpoint tests pass without modification (service mocks at orchestrator level)
- Updated service tests: `test_resolve_service.py` (8 tests), `test_refresh_bulk_service.py` (6 tests), `test_lookup_service.py` (8 tests)
