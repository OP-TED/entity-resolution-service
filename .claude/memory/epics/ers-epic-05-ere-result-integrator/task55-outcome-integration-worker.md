# Task 5: Outcome Integration Worker

## Context

The entrypoint layer — the only piece that becomes an `asyncio.Task`. Wraps the infinite
consumption loop with lifecycle management (`start` / `stop`). EPIC-07 FastAPI lifespan
calls `worker.start()` on startup and `await worker.stop()` on shutdown. The worker never
blocks the event loop — every iteration yields at `await self._listener.consume()`.

---

## Files to Create

| Path | Purpose |
|------|---------|
| `src/ers/ere_result_integrator/entrypoints/__init__.py` | Empty package marker |
| `src/ers/ere_result_integrator/entrypoints/outcome_integration_worker.py` | `OutcomeIntegrationWorker` |

---

## Step 1 — Create Package Marker

Create empty `src/ers/ere_result_integrator/entrypoints/__init__.py`.

---

## Step 2 — Implement the Worker

`src/ers/ere_result_integrator/entrypoints/outcome_integration_worker.py`:

```python
"""ERE Result Integrator background worker entrypoint (EPIC-05).

Lifecycle is managed by EPIC-07 FastAPI lifespan:
- ``worker.start()`` called during FastAPI startup (non-blocking).
- ``await worker.stop()`` called during FastAPI shutdown.

The worker runs as a single asyncio.Task on the same event loop as FastAPI
and the Resolution Coordinator (EPIC-06). This is a single-process MVP design.
"""
import asyncio
import logging

from ers.ere_result_integrator.adapters.outcome_listener import AsyncOutcomeListener
from ers.ere_result_integrator.domain.errors import (
    OutcomeValidationError,
    TriadNotFoundError,
)
from ers.ere_result_integrator.services.outcome_integration_service import (
    OutcomeIntegrationService,
)

_log = logging.getLogger(__name__)


class OutcomeIntegrationWorker:
    """Background worker that polls ERE outcomes and processes them via the service.

    Lifecycle is owned by EPIC-07 FastAPI lifespan. Call ``start()`` on app startup
    and ``await stop()`` on shutdown.

    Args:
        listener: Async outcome source (``RedisOutcomeListener`` in production).
        service: ``OutcomeIntegrationService`` wired with registry, decision store,
            and the coordinator notification callback.
    """

    def __init__(
        self,
        listener: AsyncOutcomeListener,
        service: OutcomeIntegrationService,
    ) -> None:
        self._listener = listener
        self._service = service
        self._task: asyncio.Task | None = None

    def start(self) -> asyncio.Task:
        """Schedule ``run()`` as a non-blocking background ``asyncio.Task``.

        Must be called from within a running asyncio event loop (i.e. inside
        the FastAPI lifespan context). Returns the task handle so the caller
        can cancel it on shutdown.

        Returns:
            The running ``asyncio.Task``.
        """
        self._task = asyncio.create_task(self.run(), name="outcome_integration_worker")
        return self._task

    async def stop(self) -> None:
        """Cancel the background task and await clean termination.

        Safe to call even if ``start()`` was never called or the task has
        already finished.
        """
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def run(self) -> None:
        """Infinite polling loop — pull one outcome, process it, repeat.

        ``OutcomeValidationError`` and ``TriadNotFoundError`` are logged and
        swallowed so the loop continues. All other exceptions are logged but
        also swallowed to prevent crashing the background task.
        """
        _log.info("OutcomeIntegrationWorker started")
        async for message in self._listener.consume():
            try:
                await self._service.integrate_outcome(message)
            except OutcomeValidationError as exc:
                _log.error(
                    "Contract violation — outcome rejected",
                    extra={
                        "detail": exc.detail,
                        "ere_request_id": message.ere_request_id,
                    },
                )
            except TriadNotFoundError as exc:
                _log.warning(
                    "Triad not found — outcome ignored",
                    extra={
                        "source_id": exc.identifier.source_id,
                        "request_id": exc.identifier.request_id,
                        "entity_type": exc.identifier.entity_type,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                _log.error(
                    "Unexpected error processing ERE outcome",
                    exc_info=exc,
                    extra={"ere_request_id": message.ere_request_id},
                )
```

---

## Step 3 — Write Unit Tests (UT-006)

Create `tests/unit/ere_result_integrator/entrypoints/__init__.py` (empty) and
`tests/unit/ere_result_integrator/entrypoints/test_outcome_integration_worker.py`:

```python
"""Unit tests for OutcomeIntegrationWorker — covers UT-006."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest
from erspec.models.core import EntityMentionIdentifier
from erspec.models.ere import EntityMentionResolutionResponse

from ers.ere_result_integrator.adapters.outcome_listener import AsyncOutcomeListener
from ers.ere_result_integrator.domain.errors import (
    OutcomeValidationError,
    TriadNotFoundError,
)
from ers.ere_result_integrator.entrypoints.outcome_integration_worker import (
    OutcomeIntegrationWorker,
)
from ers.ere_result_integrator.services.outcome_integration_service import (
    OutcomeIntegrationService,
)


def make_response() -> EntityMentionResolutionResponse:
    from datetime import UTC, datetime
    from erspec.models.core import ClusterReference
    return EntityMentionResolutionResponse(
        ere_request_id="req:001",
        entity_mention_id=EntityMentionIdentifier(
            source_id="S", request_id="R", entity_type="T"
        ),
        candidates=[ClusterReference(cluster_id="c", confidence_score=0.9, similarity_score=0.8)],
        timestamp=datetime.now(UTC),
    )


async def one_shot_generator(message):
    """Async generator that yields one message then stops."""
    yield message


class TestOutcomeIntegrationWorker:
    async def test_run_processes_message(self):
        """UT-006: worker calls integrate_outcome for each message from listener."""
        message = make_response()
        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.return_value = one_shot_generator(message)
        service = create_autospec(OutcomeIntegrationService, instance=True)
        service.integrate_outcome = AsyncMock(return_value=None)

        worker = OutcomeIntegrationWorker(listener=listener, service=service)
        await worker.run()

        service.integrate_outcome.assert_called_once_with(message)

    async def test_run_continues_after_validation_error(self):
        """UT-006: OutcomeValidationError is caught; loop processes next message."""
        message1 = make_response()
        message2 = make_response()

        async def two_messages():
            yield message1
            yield message2

        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.return_value = two_messages()
        service = create_autospec(OutcomeIntegrationService, instance=True)
        service.integrate_outcome = AsyncMock(
            side_effect=[OutcomeValidationError("bad"), None]
        )

        worker = OutcomeIntegrationWorker(listener=listener, service=service)
        await worker.run()

        assert service.integrate_outcome.call_count == 2

    async def test_run_continues_after_triad_not_found(self):
        """UT-006: TriadNotFoundError is caught; loop processes next message."""
        message1 = make_response()
        message2 = make_response()

        async def two_messages():
            yield message1
            yield message2

        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.return_value = two_messages()
        service = create_autospec(OutcomeIntegrationService, instance=True)
        identifier = EntityMentionIdentifier(source_id="S", request_id="R", entity_type="T")
        service.integrate_outcome = AsyncMock(
            side_effect=[TriadNotFoundError(identifier), None]
        )

        worker = OutcomeIntegrationWorker(listener=listener, service=service)
        await worker.run()

        assert service.integrate_outcome.call_count == 2

    async def test_run_continues_after_unexpected_error(self):
        """UT-006: Generic Exception is caught; loop processes next message."""
        message1 = make_response()
        message2 = make_response()

        async def two_messages():
            yield message1
            yield message2

        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.return_value = two_messages()
        service = create_autospec(OutcomeIntegrationService, instance=True)
        service.integrate_outcome = AsyncMock(
            side_effect=[RuntimeError("boom"), None]
        )

        worker = OutcomeIntegrationWorker(listener=listener, service=service)
        await worker.run()

        assert service.integrate_outcome.call_count == 2

    async def test_start_creates_task(self, event_loop):
        """start() returns a running asyncio.Task."""
        async def noop_generator():
            while True:
                await asyncio.sleep(0)
                return  # immediately stop

        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.return_value = noop_generator()
        service = create_autospec(OutcomeIntegrationService, instance=True)
        service.integrate_outcome = AsyncMock()

        worker = OutcomeIntegrationWorker(listener=listener, service=service)
        task = worker.start()
        assert isinstance(task, asyncio.Task)
        await worker.stop()

    async def test_stop_cancels_task(self):
        """stop() cancels the background task cleanly."""
        async def infinite():
            while True:
                await asyncio.sleep(1)

        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.return_value = infinite()
        service = create_autospec(OutcomeIntegrationService, instance=True)

        worker = OutcomeIntegrationWorker(listener=listener, service=service)
        worker.start()
        await worker.stop()  # must not hang
```

---

## Step 4 — Verify

```bash
poetry run pytest tests/unit/ere_result_integrator/entrypoints/ -v
```

---

## Key References

| What | Where |
|------|-------|
| `AsyncOutcomeListener` interface (Task 2) | `src/ers/ere_result_integrator/adapters/outcome_listener.py` |
| `OutcomeIntegrationService` (Task 4) | `src/ers/ere_result_integrator/services/outcome_integration_service.py` |
| EPIC-07 lifespan wiring | `.claude/memory/epics/ers-epic-07-ere-rest-api/coordination-work.md` — WORK-01 |
