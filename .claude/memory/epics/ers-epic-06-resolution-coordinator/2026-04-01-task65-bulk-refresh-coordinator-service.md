# T6.5 — BulkRefreshCoordinatorService (Spine C) — Task Outcome

**Date:** 2026-04-01
**Branch:** `feature/ERS1-145-task64` (continuing)
**Status:** Complete — 50 tests passing, pylint 10/10

## What was built

### New `exists_by_source` on `ResolutionRequestRepository`
- Abstract method added to `ResolutionRequestRepository`
- `MongoResolutionRequestRepository.exists_by_source` uses `find_one` with `{"identifiedBy.source_id": source_id}` projection `{"_id": 1}` for minimal data transfer

### `SourceNotFoundException` in `domain/exceptions.py`
- Subclasses `CoordinatorException`; stores `source_id` attribute; formats message with `!r`

### `source_has_requests` on `RequestRegistryService`
- Delegates to `_resolution_repo.exists_by_source(source_id)`
- Public traced function: span `"request_registry.source_has_requests"`

### `BulkRefreshCoordinatorService`
- File: `src/ers/resolution_coordinator/services/bulk_refresh_coordinator_service.py`
- Flow: check source exists → get lookup state → query delta → advance snapshot → return page
- `advance_snapshot` is called unconditionally (every page), consistent with `RefreshBulkService`
- `RepositoryConnectionError` propagates before snapshot advance (connection error aborts)
- Public traced function: span `"resolution_coordinator.refresh_bulk"`

## Test coverage
- `test_bulk_refresh_coordinator_service.py`: 10 tests (all spec scenarios)
- `test_exceptions.py`: 4 new `TestSourceNotFoundException` tests
- `test_request_registry_service.py`: 2 new `TestSourceHasRequests` tests

## Key decisions
- `too-few-public-methods` suppressed inline on `BulkRefreshCoordinatorService` — idiomatic single-method service class pattern
- Call-order verification via `side_effect` tracker list (`["delta", "snapshot"]`) rather than mock call index manipulation
