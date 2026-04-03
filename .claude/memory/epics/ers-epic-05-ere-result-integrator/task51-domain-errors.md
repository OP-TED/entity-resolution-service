# Task 1: Domain Errors

## Context

First step — no dependencies. Creates the `ere_result_integrator` package and its two domain
error classes. Both subclass `ApplicationError` from `ers.commons.services.exceptions`,
following the same pattern as EPIC-01 and EPIC-04 errors.

---

## Files to Create

| Path | Purpose |
|------|---------|
| `src/ers/ere_result_integrator/__init__.py` | Empty package marker |
| `src/ers/ere_result_integrator/domain/__init__.py` | Empty package marker |
| `src/ers/ere_result_integrator/domain/errors.py` | `OutcomeValidationError`, `TriadNotFoundError` |

---

## Step 1 — Create Package Markers

Create empty `__init__.py` files:
- `src/ers/ere_result_integrator/__init__.py`
- `src/ers/ere_result_integrator/domain/__init__.py`

---

## Step 2 — Implement Domain Errors

`src/ers/ere_result_integrator/domain/errors.py`:

```python
"""Domain errors for the ERE Result Integrator (EPIC-05).

Both errors subclass ApplicationError to integrate with the existing
ERS exception hierarchy and FastAPI exception handlers.
"""
from erspec.models.core import EntityMentionIdentifier

from ers.commons.services.exceptions import ApplicationError


class OutcomeValidationError(ApplicationError):
    """Raised when an ERE response fails contract validation.

    Triggered by:
    - ``response.timestamp`` is ``None``
    - ``response.candidates`` is empty

    Args:
        detail: Human-readable description of the validation failure.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class TriadNotFoundError(ApplicationError):
    """Raised when the correlation triad is not found in the Request Registry.

    Outcome is logged at WARN level and ignored — the Decision Store is not modified.

    Args:
        identifier: The triad that could not be resolved.
    """

    def __init__(self, identifier: EntityMentionIdentifier) -> None:
        self.identifier = identifier
        super().__init__(
            f"Triad not found: ({identifier.source_id}, "
            f"{identifier.request_id}, {identifier.entity_type})"
        )
```

---

## Step 3 — Verify

```bash
poetry run python -c "
from ers.ere_result_integrator.domain.errors import OutcomeValidationError, TriadNotFoundError
from erspec.models.core import EntityMentionIdentifier
e1 = OutcomeValidationError('null timestamp')
assert e1.detail == 'null timestamp'
id_ = EntityMentionIdentifier(source_id='s', request_id='r', entity_type='t')
e2 = TriadNotFoundError(id_)
assert e2.identifier is id_
print('OK')
"
```

---

## Key References

| What | Where |
|------|-------|
| `ApplicationError` base class | `src/ers/commons/services/exceptions.py` |
| EPIC-01 error pattern reference | `src/ers/request_registry/services/exceptions.py` |
| EPIC-04 error pattern reference | `src/ers/resolution_decision_store/domain/errors.py` |
