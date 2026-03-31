# Task 6.4 — DecisionStoreService Delta Extension

## Goal

Add `query_decisions_delta` to `DecisionStoreService` so that
`BulkRefreshCoordinatorService` (Task 6.5) can retrieve only the decisions that
changed since a source's last snapshot — the delta query at the heart of Spine C.

This task touches one existing service file and one test file. No repository changes
unless `DecisionFilters` genuinely cannot express the required filters (see design note).

---

## Context

The existing `DecisionStoreService.query_decisions_paginated` performs a global
cursor-paginated scan with no filtering. Spine C needs a filtered variant:

> *"Give me all decisions for source `SYSTEM_A` whose `updated_at` is after
> `2026-03-12T10:00:00Z`, paginated by cursor."*

The underlying `MongoDecisionRepository.find_with_filters` already accepts a
`DecisionFilters` object and `CursorParams`. Whether `DecisionFilters` already
carries `source_id` and `updated_since` fields must be verified before writing code.

---

## Pre-Implementation Check (Do This First)

Read `src/ers/commons/domain/data_transfer_objects.py` and locate `DecisionFilters`.

**Case A — `DecisionFilters` already has `source_id` and `updated_since` (or equivalent):**
Proceed directly to implementing `query_decisions_delta` using `find_with_filters`.

**Case B — `DecisionFilters` is missing one or both fields:**
Add the missing fields to `DecisionFilters` (it is a shared domain DTO — adding
optional fields with `None` defaults is backwards-compatible and safe).
Do NOT add a raw MongoDB query in the service — keep the service/adapter boundary intact.

**Case C — `find_with_filters` does not accept the required filter semantics at all:**
Flag this to the developer before proceeding. Do not work around it by putting
query logic in the service layer.

---

## Scope

### What to build

**New method on `DecisionStoreService`:**

```python
async def query_decisions_delta(
    self,
    source_id: str,
    updated_since: datetime | None,
    cursor: str | None = None,
    page_size: int | None = None,
) -> CursorPage[Decision]:
    """Return decisions for a source updated after updated_since, paginated by cursor.

    Used by BulkRefreshCoordinatorService to compute the delta since the last
    snapshot for a given source system.

    Args:
        source_id: The source system identifier to filter by.
        updated_since: If provided, only decisions with updated_at > updated_since
            are returned. If None, all decisions for the source are returned
            (first-time lookup — source has no snapshot yet).
        cursor: Opaque pagination token from a previous response, or None for
            the first page.
        page_size: Max results per page. Capped at the system pagination limit.

    Returns:
        A CursorPage with matching Decisions and an optional next_cursor.

    Raises:
        InvalidCursorError: If the cursor string cannot be decoded.
        RepositoryConnectionError: On MongoDB connection failure.
    """
    effective_size = min(
        page_size if page_size is not None else config.DECISION_STORE_DEFAULT_PAGE_SIZE,
        MAX_PER_PAGE,
    )
    filters = DecisionFilters(source_id=source_id, updated_since=updated_since)
    return await self._repository.find_with_filters(
        filters=filters,
        cursor_params=CursorParams(cursor=cursor, limit=effective_size),
    )
```

**New public module-level function (traced):**

```python
@trace_function(span_name="decision_store.query_delta")
async def query_decisions_delta(
    source_id: str,
    updated_since: datetime | None,
    service: DecisionStoreService,
    cursor: str | None = None,
    page_size: int | None = None,
) -> CursorPage[Decision]:
    """Return the delta of changed decisions for a source since a snapshot point.

    Args:
        source_id: The source system to query.
        updated_since: Lower-bound timestamp (exclusive). None means all decisions.
        service: The DecisionStoreService instance.
        cursor: Pagination cursor, or None for first page.
        page_size: Max results per page.

    Returns:
        A CursorPage of matching Decisions.

    Raises:
        InvalidCursorError: If the cursor is malformed.
        RepositoryConnectionError: On MongoDB connection failure.
    """
    return await service.query_decisions_delta(
        source_id=source_id,
        updated_since=updated_since,
        cursor=cursor,
        page_size=page_size,
    )
```

Place both in `src/ers/resolution_decision_store/services/decision_store_service.py`,
following the existing method/function ordering pattern in that file.

### What NOT to build
- No changes to `MongoDecisionRepository` unless `DecisionFilters` needs new fields
  (Case B above — add fields to the DTO, not raw queries to the repository)
- No new service class — this is an extension of the existing `DecisionStoreService`
- No changes to `ResolutionDecisionStoreServiceABC` — that temp ABC is being retired
  in Task 6.7; do not propagate new methods into it

---

## Files to Create / Modify

| Action | File |
|--------|------|
| Modify | `src/ers/resolution_decision_store/services/decision_store_service.py` |
| Modify (if Case B) | `src/ers/commons/domain/data_transfer_objects.py` — add fields to `DecisionFilters` |
| Create | `tests/unit/resolution_decision_store/services/test_decision_store_delta.py` |

Do NOT modify the existing `test_decision_store_service.py` — add a separate file for
the delta tests to keep concerns isolated.

---

## Unit Tests

File: `tests/unit/resolution_decision_store/services/test_decision_store_delta.py`

All tests mock `MongoDecisionRepository` with `AsyncMock(spec=MongoDecisionRepository)`.

| Test | Scenario | Key assertion |
|------|----------|---------------|
| `test_delta_with_snapshot` | `source_id="SRC_A"`, `updated_since=t0` | `find_with_filters` called with `DecisionFilters(source_id="SRC_A", updated_since=t0)` |
| `test_delta_without_snapshot` | `updated_since=None` | `find_with_filters` called with `DecisionFilters(source_id=..., updated_since=None)` — returns all decisions for source |
| `test_delta_returns_page` | Repository returns 3 decisions | Method returns same `CursorPage` unchanged |
| `test_delta_returns_empty_page` | Repository returns empty page | Method returns empty `CursorPage` |
| `test_delta_respects_page_size_cap` | `page_size=99999` | `CursorParams.limit` capped at `MAX_PER_PAGE` |
| `test_delta_uses_default_page_size` | `page_size=None` | `CursorParams.limit` = `config.DECISION_STORE_DEFAULT_PAGE_SIZE` |
| `test_delta_passes_cursor` | `cursor="opaque-token"` | `CursorParams.cursor` = `"opaque-token"` |
| `test_delta_propagates_connection_error` | `find_with_filters` raises `RepositoryConnectionError` | Exception propagates unchanged |

Example:
```python
async def test_delta_with_snapshot(mock_repo):
    svc = DecisionStoreService(repository=mock_repo)
    t0 = datetime(2026, 3, 12, 10, 0, 0, tzinfo=UTC)
    mock_repo.find_with_filters.return_value = CursorPage(items=[], next_cursor=None)

    await svc.query_decisions_delta(source_id="SRC_A", updated_since=t0)

    mock_repo.find_with_filters.assert_awaited_once()
    call_kwargs = mock_repo.find_with_filters.call_args.kwargs
    assert call_kwargs["filters"].source_id == "SRC_A"
    assert call_kwargs["filters"].updated_since == t0
```

---

## Definition of Done

- [ ] Pre-implementation check completed and Case A/B/C documented in a comment at the top of the test file
- [ ] `DecisionStoreService.query_decisions_delta` method exists and is covered by all 8 unit tests
- [ ] Public `query_decisions_delta` function exists with `@trace_function` decorator
- [ ] All unit tests pass: `poetry run pytest tests/unit/resolution_decision_store/services/test_decision_store_delta.py -v`
- [ ] Existing `DecisionStoreService` tests still pass (no regressions): `poetry run pytest tests/unit/resolution_decision_store/ -v`
- [ ] `poetry run pylint src/ers/resolution_decision_store/services/decision_store_service.py` — no new errors
