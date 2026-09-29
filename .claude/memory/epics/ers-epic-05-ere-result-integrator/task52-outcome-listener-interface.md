# Task 2: Outcome Listener Interface

## Context

Defines the framework-agnostic abstraction for ERE outcome consumption. The interface
exposes `consume()` as an async generator — callers iterate over it indefinitely.
Concrete implementations (Task 3) swap the backend without touching the service layer.

---

## Files to Create

| Path | Purpose |
|------|---------|
| `src/ers/ere_result_integrator/adapters/__init__.py` | Empty package marker |
| `src/ers/ere_result_integrator/adapters/outcome_listener.py` | `AsyncOutcomeListener` ABC |

---

## Step 1 — Create Package Marker

Create empty `src/ers/ere_result_integrator/adapters/__init__.py`.

---

## Step 2 — Implement the Interface

`src/ers/ere_result_integrator/adapters/outcome_listener.py`:

```python
"""Abstract interface for ERE outcome consumption (EPIC-05).

Concrete implementations wrap a specific messaging backend (Redis, Kafka, etc.)
and yield EntityMentionResolutionResponse objects one at a time. The service layer
depends only on this interface — never on a concrete implementation.
"""
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from erspec.models.ere import EntityMentionResolutionResponse


class AsyncOutcomeListener(ABC):
    """Framework-agnostic interface for async ERE outcome consumption.

    Implementations must yield only ``EntityMentionResolutionResponse`` objects.
    Error responses (``EREErrorResponse``) are handled inside the implementation
    and must not be yielded.
    """

    @abstractmethod
    def consume(self) -> AsyncGenerator[EntityMentionResolutionResponse, None]:
        """Yield ERE resolution responses as they arrive.

        Runs indefinitely — callers are responsible for cancelling the task
        (via ``OutcomeIntegrationWorker.stop()``) when shutting down.

        Yields:
            EntityMentionResolutionResponse: Each valid response from the ERE.
        """
```

---

## Step 3 — Verify

```bash
poetry run python -c "
from ers.ere_result_integrator.adapters.outcome_listener import AsyncOutcomeListener
from abc import ABC
assert issubclass(AsyncOutcomeListener, ABC)
print('OK')
"
```

---

## Key References

| What | Where |
|------|-------|
| `EntityMentionResolutionResponse` (erspec) | `erspec/models/ere.py` |
| `AbstractClient` (reference for async pattern) | `src/ers/commons/adapters/redis_client.py` |
