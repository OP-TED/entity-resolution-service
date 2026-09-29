# Task 5: Unit Tests Gap Fill

## Context

Unit tests were written via TDD throughout Tasks 3 and 4. Two specified test cases from Section 8 of the EPIC are still missing. This task closes those gaps and marks the unit test suite complete.

---

## Missing Tests

### TC-013 — Empty collection returns empty page

Add to `tests/unit/resolution_decision_store/adapters/test_decision_repository.py`:

```python
@pytest.mark.asyncio
async def test_find_with_filters_empty_collection_returns_empty_page(repo, mock_collection):
    async def async_generator():
        return
        yield  # make it an async generator

    cursor_mock = MagicMock()
    cursor_mock.sort.return_value = cursor_mock
    cursor_mock.limit.return_value = cursor_mock
    cursor_mock.__aiter__ = lambda self: async_generator()

    mock_collection.find = MagicMock(return_value=cursor_mock)

    page = await repo.find_with_filters(filters=None, cursor_params=CursorParams(cursor=None, limit=3))
    assert len(page.results) == 0
    assert page.next_cursor is None
```

### TC-017 — Service propagates `InvalidCursorError` from repository

Add to `tests/unit/resolution_decision_store/services/test_decision_store_service.py`:

```python
# In class TestQueryDecisionsPaginated:
async def test_propagates_invalid_cursor_error(self, service, mock_repo):
    from ers.commons.domain.exceptions import InvalidCursorError
    mock_repo.find_with_filters.side_effect = InvalidCursorError("bad cursor")
    with pytest.raises(InvalidCursorError):
        await service.query_decisions_paginated(cursor="bad-cursor-value")
```

---

## After Adding Tests

Also update the EPIC roadmap:
- Mark Task 4 complete: `- [x] Task 4: Implement Service Layer (services/) (2026-03-24)`
- Mark Task 5 complete: `- [x] Task 5: Unit Tests (tests/unit/) (2026-03-24)`

---

## Verify

```bash
poetry run pytest tests/unit/resolution_decision_store/ -v
```

All tests must pass (should be 34 total: 32 existing + 2 new).
