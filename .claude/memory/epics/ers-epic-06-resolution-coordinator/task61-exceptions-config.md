# Task 6.1 — Foundation: Exceptions + Config

## Goal

Establish the exception hierarchy and configuration entries for the Resolution Coordinator.
This is the zero-dependency foundation that all subsequent tasks import from.

---

## Scope

### What to build

**1. Exception hierarchy**
File: `src/ers/resolution_coordinator/domain/exceptions.py`

```
CoordinatorException(ApplicationError)           ← base for all coordinator errors
├── ResolutionTimeoutException(CoordinatorException)
├── ParsingFailedException(CoordinatorException)
└── EnginePublishFailedException(CoordinatorException)
```

`ApplicationError` is from `ers.commons.services.exceptions`. It is the correct base for
service-layer exceptions. `DomainError` (`ers.commons.domain.exceptions`) is for pure
domain invariants and must NOT be used here.

Each exception:
- Accepts `message: str` in `__init__` and calls `super().__init__(message)`
- `ParsingFailedException` additionally accepts `cause: Exception`, stored as `self.cause`
  (so callers can inspect the original parser error if needed)
- `EnginePublishFailedException` additionally accepts `cause: Exception`, stored as `self.cause`

**2. Config entries**
File: `src/ers/__init__.py` — add a new `ResolutionCoordinatorConfig` class following the
exact `env_property` pattern already used by all other config classes in that file.

Two config values — one per request shape:

```python
class ResolutionCoordinatorConfig:

    @env_property(default_value="30")
    def ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET(self, config_value: str) -> float:
        """Maximum time budget for a single-mention resolution response.
        Also serves as the ERE wait window — if ERE does not respond within
        this budget, a provisional identifier is issued and returned to the client."""
        return float(config_value)

    @env_property(default_value="120")
    def ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET(self, config_value: str) -> float:
        """Maximum time budget for a bulk resolution response (all mentions combined).
        Each mention waits up to SINGLE_REQUEST_TIME_BUDGET for ERE internally."""
        return float(config_value)
```

Add `ResolutionCoordinatorConfig` to `ERSConfigResolver`'s base class list.

### What NOT to build
- No `CoordinatorConfig` Pydantic model — config lives in the project-wide `ERSConfigResolver`
- No service classes, no repository, no adapter
- No cross-field validation (window < single budget) — that is a runtime guard in
  `ResolutionCoordinatorService.__init__` (Task 6.3), not in the config declaration

---

## Key Decisions

- **Two budgets, not three:** `SINGLE_REQUEST_TIME_BUDGET` doubles as the ERE wait window.
  No separate ERE window config. On timeout, a provisional is issued — not a fatal exception.
  `ResolutionTimeoutException` is reserved for failures where even issuing a provisional
  is impossible (e.g. MongoDB down while writing provisional).
- **Naming convention:** `...Exception` suffix throughout. NOT `...Error` as in the EPIC spec.
- **Base class:** `CoordinatorException` → `ApplicationError` (service-layer, not domain-layer).
- **`cause` parameter:** Stored but not re-raised. The coordinator maps third-party exceptions
  into its own vocabulary at the boundary; callers only see coordinator exceptions.
- **Config defaults:** 30s single, 120s bulk.

---

## Files to Create / Modify

| Action | File |
|--------|------|
| Create | `src/ers/resolution_coordinator/domain/__init__.py` |
| Create | `src/ers/resolution_coordinator/domain/exceptions.py` |
| Modify | `src/ers/__init__.py` — add `ResolutionCoordinatorConfig` + extend `ERSConfigResolver` |
| Create | `tests/unit/resolution_coordinator/__init__.py` |
| Create | `tests/unit/resolution_coordinator/domain/__init__.py` |
| Create | `tests/unit/resolution_coordinator/domain/test_exceptions.py` |

---

## Unit Tests

File: `tests/unit/resolution_coordinator/domain/test_exceptions.py`

Cover:
- Each exception is instantiable with a message string
- Each exception is a subclass of `CoordinatorException`
- `CoordinatorException` is a subclass of `ApplicationError` from `ers.commons.services.exceptions`
- `ParsingFailedException` stores the `cause` attribute correctly
- `EnginePublishFailedException` stores the `cause` attribute correctly
- Config: `ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET` defaults to `30.0`
- Config: `ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET` defaults to `120.0`
- Config: both fields respond to environment variable overrides
  (use `monkeypatch.setenv` + a fresh `ERSConfigResolver()` instance to avoid polluting
  the global `config` singleton)

No mocking needed — all tests are pure unit tests.

---

## Definition of Done

- [ ] `src/ers/resolution_coordinator/domain/exceptions.py` exists with all four classes
- [ ] `ERSConfigResolver` includes `ResolutionCoordinatorConfig` as a base
- [ ] `from ers import config; config.ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET` → `30.0`
- [ ] `from ers import config; config.ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET` → `120.0`
- [ ] All unit tests pass: `poetry run pytest tests/unit/resolution_coordinator/domain/ -v`
- [ ] `poetry run pylint src/ers/resolution_coordinator/domain/` — no errors
- [ ] `poetry run python -c "from ers.resolution_coordinator.domain.exceptions import CoordinatorException"` succeeds
