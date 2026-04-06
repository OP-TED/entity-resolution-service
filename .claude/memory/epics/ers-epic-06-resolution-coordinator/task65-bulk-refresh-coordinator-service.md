# Task 6.5 — BulkRefreshCoordinatorService (Spine C)

## Goal

Implement `BulkRefreshCoordinatorService` — the orchestrator for Spine C bulk cluster
assignment lookups. A source system calls this to retrieve all decisions that have changed
since its last snapshot, page by page.

---

## Scope

### What to build

Three things are needed in this task:

**1. One new exception** — add to `src/ers/resolution_coordinator/domain/exceptions.py`
(extending the hierarchy from Task 6.1, no new file needed):

```python
class SourceNotFoundException(CoordinatorException):
    """Raised when the requested source has no resolution requests in the Registry.

    Args:
        source_id: The source identifier that was not found.
    """
    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        super().__init__(f"Source not found in registry: {source_id!r}")
```

**2. One new method on `RequestRegistryService`** — in
`src/ers/request_registry/services/request_registry_service.py`:

```python
async def source_has_requests(self, source_id: str) -> bool:
    """Return True if at least one resolution request exists for the given source.

    Args:
        source_id: The source system identifier.

    Returns:
        True if any record with this source_id exists in the registry.
    """
    return await self._resolution_repo.exists_by_source(source_id)
```

Add the corresponding public module-level function with `@trace_function`.

The underlying repository query (count by source_id) is an implementation detail owned
by `RequestRegistryService` and its adapter — do NOT call the repository or any adapter
directly from `BulkRefreshCoordinatorService`. If `MongoResolutionRequestRepository`
lacks the needed query, add it as a private concern of `RequestRegistryService`.

**3. `BulkRefreshCoordinatorService`** — new file:
`src/ers/resolution_coordinator/services/bulk_refresh_coordinator_service.py`

---

## Flow: `refresh_bulk`

```python
async def refresh_bulk(
    self,
    source_id: str,
    cursor: str | None = None,
    page_size: int | None = None,
) -> CursorPage[Decision]:
```

Step-by-step:

```
1. CHECK SOURCE EXISTS
   exists = await registry_service.source_has_requests(source_id)
   if not exists:
       raise SourceNotFoundException(source_id)

2. GET LAST SNAPSHOT
   lookup_state = await registry_service.get_lookup_state(source_id)
   updated_since = lookup_state.last_snapshot if lookup_state else None
   # None means first-time lookup — return all decisions for this source

3. QUERY DELTA
   page = await decision_store_service.query_decisions_delta(
       source_id=source_id,
       updated_since=updated_since,
       cursor=cursor,
       page_size=page_size,
   )
   # RepositoryConnectionError propagates as-is → caller maps to service error

4. ADVANCE SNAPSHOT
   await registry_service.advance_snapshot(source_id, datetime.now(UTC))
   # SnapshotRegressionError propagates — should not happen in normal flow
   # (concurrent bulk requests by the same source are a caller responsibility)

5. RETURN PAGE
   return page
```

**Read-only invariant:** This method never calls `EREPublishService`,
`store_decision`, or `register_resolution_request`. It is purely a read + snapshot
advance. Any code path that touches ERE or writes a Decision is a bug.

**Snapshot advance policy:** `advance_snapshot` is called on every page by default
(consistent with the existing `RefreshBulkService`). This is a single-line behaviour
controlled by whether `advance_snapshot` is called before or after checking `has_more`.
Keep the call unconditional for now — switching to "last page only" is a one-line change
if requirements change.

---

## Service Class

```python
class BulkRefreshCoordinatorService:

    def __init__(
        self,
        registry_service: RequestRegistryService,
        decision_store_service: DecisionStoreService,
    ) -> None:
        self._registry_service = registry_service
        self._decision_store_service = decision_store_service

    async def refresh_bulk(
        self,
        source_id: str,
        cursor: str | None = None,
        page_size: int | None = None,
    ) -> CursorPage[Decision]:
        ...
```

Config is NOT needed here — no timeouts. Bulk refresh is a synchronous read-then-respond
operation; the HTTP layer enforces any request timeout.

**Public module-level API:**

```python
@trace_function(span_name="resolution_coordinator.refresh_bulk")
async def refresh_bulk(
    source_id: str,
    service: BulkRefreshCoordinatorService,
    cursor: str | None = None,
    page_size: int | None = None,
) -> CursorPage[Decision]:
    """Retrieve the delta of changed cluster assignments for a source.

    Args:
        source_id: The source system to query.
        service: The BulkRefreshCoordinatorService instance.
        cursor: Pagination cursor, or None for the first page.
        page_size: Max results per page.

    Returns:
        A CursorPage of Decisions updated since the last snapshot.

    Raises:
        SourceNotFoundException: If the source has no requests in the registry.
        RepositoryConnectionError: If the Decision Store is unavailable.
    """
    return await service.refresh_bulk(source_id, cursor=cursor, page_size=page_size)
```

---

## Files to Create / Modify

| Action | File |
|--------|------|
| Modify | `src/ers/resolution_coordinator/domain/exceptions.py` — add `SourceNotFoundException` |
| Modify | `src/ers/request_registry/services/request_registry_service.py` — add `source_has_requests` method + public function |
| Modify (if needed) | `src/ers/request_registry/adapters/records_repository.py` — add `exists_by_source` **only if** the service method cannot be implemented without it; the adapter change is a private concern of the request registry package |
| Create | `src/ers/resolution_coordinator/services/bulk_refresh_coordinator_service.py` |
| Create | `tests/unit/resolution_coordinator/services/test_bulk_refresh_coordinator_service.py` |
| Modify | `tests/unit/resolution_coordinator/domain/test_exceptions.py` — add `SourceNotFoundException` test |
| Modify | `tests/unit/request_registry/services/test_request_registry_service.py` — add `source_has_requests` tests |

---

## Unit Tests

### `test_bulk_refresh_coordinator_service.py`

All tests mock both `RequestRegistryService` and `DecisionStoreService` with `AsyncMock`.
`source_has_requests` returns `True` by default unless the test specifies otherwise.

| Test | Scenario | Key assertion |
|------|----------|---------------|
| `test_returns_delta_with_prior_snapshot` | Lookup state exists with `last_snapshot=t0` | `query_decisions_delta` called with `updated_since=t0`; snapshot advanced |
| `test_returns_all_on_first_lookup` | `get_lookup_state` returns None | `query_decisions_delta` called with `updated_since=None` |
| `test_empty_delta_still_advances_snapshot` | Delta page is empty | `advance_snapshot` still called; empty page returned |
| `test_unknown_source_raises` | `source_has_requests` returns False | `SourceNotFoundException` raised; `query_decisions_delta` NOT called |
| `test_decision_store_unavailable` | `query_decisions_delta` raises `RepositoryConnectionError` | `RepositoryConnectionError` propagates; `advance_snapshot` NOT called |
| `test_read_only_no_publish` | Happy path | `publish_request` is not a dependency → verifiable by constructor signature |
| `test_read_only_no_store_decision` | Happy path | `store_decision` not a dependency → verifiable by constructor signature |
| `test_snapshot_advanced_after_delta` | Happy path | `advance_snapshot` called AFTER `query_decisions_delta` (use `AsyncMock` call order) |
| `test_cursor_and_page_size_forwarded` | `cursor="tok"`, `page_size=50` | `query_decisions_delta` called with same `cursor` and `page_size` |
| `test_returns_page_unchanged` | Repository returns 3 decisions | Returned `CursorPage` is identical to what repository returned |

Example for call-order test:
```python
async def test_snapshot_advanced_after_delta(registry_svc, decision_svc):
    svc = BulkRefreshCoordinatorService(registry_svc, decision_svc)
    registry_svc.source_has_requests.return_value = True
    registry_svc.get_lookup_state.return_value = None
    decision_svc.query_decisions_delta.return_value = CursorPage(items=[], next_cursor=None)

    await svc.refresh_bulk("SRC_A")

    # Verify ordering via call index on the mock manager
    from unittest.mock import call
    delta_idx = decision_svc.method_calls.index(call.query_decisions_delta(...))
    snap_idx  = registry_svc.method_calls.index(call.advance_snapshot(...))
    assert delta_idx < snap_idx
```

(Adjust to the actual mock call-order verification style used elsewhere in the project.)

### Additional tests in existing files

`test_request_registry_service.py` — add:
- `test_source_has_requests_true`: mock repo returns count > 0 → returns True
- `test_source_has_requests_false`: mock repo returns 0 → returns False

`test_exceptions.py` — add:
- `test_source_not_found_exception_message`: verify `SourceNotFoundException("X").source_id == "X"`
- `test_source_not_found_is_coordinator_exception`: isinstance check

---

## Definition of Done

- [ ] `SourceNotFoundException` exists in `domain/exceptions.py` and is tested
- [ ] `RequestRegistryService.source_has_requests` exists, is tested, and has a public traced function
- [ ] `BulkRefreshCoordinatorService.refresh_bulk` implements all 6 Spine C scenarios
- [ ] All 10 unit tests pass: `poetry run pytest tests/unit/resolution_coordinator/services/test_bulk_refresh_coordinator_service.py -v`
- [ ] Read-only invariant provable from constructor (no ERE or write dependencies injected)
- [ ] Existing request registry tests still pass: `poetry run pytest tests/unit/request_registry/ -v`
- [ ] `poetry run pylint src/ers/resolution_coordinator/services/bulk_refresh_coordinator_service.py` — no errors
