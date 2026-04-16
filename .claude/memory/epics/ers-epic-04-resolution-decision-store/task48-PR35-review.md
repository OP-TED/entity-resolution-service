# Task 48 — PR #35 Code Review Outcomes

**PR:** [#35 — Resolution Decision Store (EPIC-04)](https://github.com/meaningfy-ws/entity-resolution-service/pull/35)
**Review comment:** https://github.com/meaningfy-ws/entity-resolution-service/pull/35#issuecomment-4129772751
**Date:** 2026-03-25
**Status:** Changes required before merge

---

## Issues Found

---

### Issue 1 — Old stub test suite still active (Critical)

**File:** `tests/feature/decision_store/test_decision_persistence.py` and `test_paginated_query.py`

**What is wrong:**
The directory `tests/feature/decision_store/` is the pre-implementation skeleton that was never completed and never removed. Every `@then` and `@when` step contains `assert True  # TODO: implement`, and the service is never instantiated (`ctx["service"] = None  # TODO`). These scenarios will appear green in CI while exercising nothing.

Two test trees now coexist covering the same module:
- `tests/feature/decision_store/` — dead stubs
- `tests/feature/resolution_decision_store/` — real implementation

**Why it is an issue:**
Dead stub tests that always pass create false confidence. The project convention (`~/.claude/CLAUDE.md §4`, CLAUDE.md "Working Methodology") requires that test runs produce meaningful signal. CI green on stubs is noise, not safety.

**What must be done:**
Delete `tests/feature/decision_store/` entirely. Confirm every scenario from the old feature files is already covered in `tests/feature/resolution_decision_store/`. If any scenario is absent there, migrate it with a real step definition.

---

### Issue 2 — Page-size capped at 50 instead of configured 1000 (Critical)

**File:** `src/ers/resolution_decision_store/services/decision_store_service.py`, line ~90
**Also:** `src/ers/commons/domain/data_transfer_objects.py`, `CursorParams`

**What is wrong:**
`query_decisions_paginated` caps `effective_size` against `MAX_PER_PAGE = 50`, a curation API constant from commons, instead of `config.DECISION_STORE_MAX_PAGE_SIZE` (default 1000). Additionally, `CursorParams` is declared with `le=MAX_PER_PAGE`, so any caller requesting more than 50 records raises a Pydantic `ValidationError` before the cap is even applied.

The EPIC spec (§4.2, §5.3) mandates `default_page_size=250`, `max_page_size=1000`. The configured values `DECISION_STORE_DEFAULT_PAGE_SIZE` and `DECISION_STORE_MAX_PAGE_SIZE` are effectively dead code. A `# FIXME` comment in `data_transfer_objects.py` acknowledges this but leaves it unresolved. The docstring at the module-level function says "Capped at `DECISION_STORE_MAX_PAGE_SIZE`" — directly contradicting the implementation.

**Why it is an issue:**
Bulk sync callers (EPIC-07) require pages up to 1000. They will receive at most 50 records per call — 20× more API calls than designed. The component cannot fulfil its bulk-sync responsibility as specified.

**What must be done:**
Introduce a Decision Store-specific `CursorParams` subclass (or adjust the cap) so `limit` is bounded by `DECISION_STORE_MAX_PAGE_SIZE`. Remove the dependency on `MAX_PER_PAGE` in the Decision Store service. The FIXME in commons must also be resolved — `MAX_PER_PAGE = 50` is a curation REST API constraint and must not leak into bulk-sync infrastructure.

Hint: define a `DecisionStoreCursorParams(CursorParams)` that overrides the `le` constraint, or pass the cap explicitly in service logic without relying on `CursorParams` validation for enforcement.

---

### Issue 3 — Candidate truncation BDD scenario passes vacuously (High)

**File:** `tests/feature/resolution_decision_store/test_store_decision.py`, lines ~99–192

**What is wrong:**
The scenario "Candidates are truncated to max_candidates" builds 10 candidates but the mock returns `make_decision(now)` which defaults to `candidates=[]`. The `@then` step asserts `len(ctx["result"].candidates) <= config.DECISION_STORE_MAX_CANDIDATES`, which evaluates to `0 <= 5` — trivially true. The truncation logic in `DecisionStoreService.store_decision` is never actually verified: the test would pass even if the truncation line were deleted.

**Why it is an issue:**
Truncation is a stated EPIC invariant (§4.2, §5.1, TC-017). A passing test that does not exercise the invariant is worse than no test — it misleads reviewers and blocks regression detection.

**What must be done:**
After `store_decision` is called, inspect what was actually passed to the repository:
```python
call_kwargs = mock_repo.upsert_decision.call_args.kwargs
assert len(call_kwargs["candidates"]) <= config.DECISION_STORE_MAX_CANDIDATES
```
Alternatively, configure `make_decision` to return the candidates it receives so the result assertion is meaningful.

---

### Issue 4 — `InvalidCursorError` missing from `domain/errors.py` (Medium)

**File:** `src/ers/resolution_decision_store/domain/errors.py`

**What is wrong:**
The EPIC spec Section 6 error catalogue explicitly defines `InvalidCursorError` as a service-layer error for the Resolution Decision Store, to be placed in `domain/errors.py` and to inherit from `DecisionStoreError`. The file contains `StaleOutcomeError`, `DecisionNotFoundError`, `RepositoryConnectionError`, and `RepositoryOperationError` — but not `InvalidCursorError`.

A generic `InvalidCursorError` exists in `ers.commons.domain.exceptions` with a hardcoded message and no connection to `DecisionStoreError`. The service docstring documents `InvalidCursorError` in its `Raises:` section, implying callers should catch it, but there is no domain-specific version they can import from this module.

**Why it is an issue:**
The EPIC spec and the project coding standard (`~/.claude/CLAUDE.md §2.4` — structured domain errors) both require module-specific error subclasses in `domain/errors.py`. Callers of the Decision Store service cannot catch a Decision-Store-scoped error — they catch the generic commons one, which conflates cursor errors from different modules.

**What must be done:**
Add `InvalidCursorError(DecisionStoreError)` to `src/ers/resolution_decision_store/domain/errors.py`. In `query_decisions_paginated`, catch the commons `InvalidCursorError` raised by `decode_cursor()` and re-raise it as the domain-specific subclass so callers receive a properly scoped error.

---

## Summary Table

| # | Severity | File | Fix location |
|---|----------|------|-------------|
| 1 | Critical | `tests/feature/decision_store/` | Delete directory; verify coverage in `resolution_decision_store/` |
| 2 | Critical | `decision_store_service.py:~90`, `data_transfer_objects.py` | Introduce Decision Store-specific cursor params; cap against config, not `MAX_PER_PAGE` |
| 3 | High | `test_store_decision.py:~188` | Assert on `mock_repo.upsert_decision.call_args`, not on the mock return value |
| 4 | Medium | `domain/errors.py` | Add `InvalidCursorError(DecisionStoreError)` and re-raise in service |