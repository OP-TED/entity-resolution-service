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
    integrate_outcome,
)

_log = logging.getLogger(__name__)

_BACKOFF_INITIAL = 1.0
_BACKOFF_CAP = 30.0


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
        """Polling loop - pull one outcome, process it, repeat.

        Restarts automatically after a Redis ``ConnectionError`` using
        exponential backoff (1s -> 2s -> 4s ... capped at 30s). Backoff resets
        to 1s after any successful message receive.
        ``OutcomeValidationError`` and ``TriadNotFoundError`` are logged and
        swallowed so the loop continues. Infrastructure ``ConnectionError`` from
        the service layer (registry / decision store) is logged distinctly and
        swallowed. All other exceptions are logged and swallowed to prevent
        crashing the background task.
        """
        _log.info("OutcomeIntegrationWorker started")
        backoff = _BACKOFF_INITIAL
        try:
            while True:
                try:
                    async for message in self._listener.consume():
                        backoff = _BACKOFF_INITIAL
                        try:
                            await integrate_outcome(message, self._service)
                        except OutcomeValidationError as exc:
                            _log.error(
                                "Contract violation - outcome rejected",
                                extra={
                                    "detail": exc.detail,
                                    "ere_request_id": message.ere_request_id,
                                },
                            )
                        except TriadNotFoundError as exc:
                            _log.warning(
                                "Triad not found - outcome ignored",
                                extra={
                                    "source_id": exc.identifier.source_id,
                                    "request_id": exc.identifier.request_id,
                                    "entity_type": exc.identifier.entity_type,
                                },
                            )
                        except ConnectionError as exc:
                            _log.error(
                                "Infrastructure connection error - outcome may be retried on restart",
                                exc_info=exc,
                                extra={"ere_request_id": message.ere_request_id},
                            )
                        except Exception as exc:
                            _log.error(
                                "Unexpected error processing ERE outcome",
                                exc_info=exc,
                                extra={"ere_request_id": message.ere_request_id},
                            )
                    break  # listener exhausted normally (test or graceful shutdown)
                except ConnectionError as exc:
                    _log.error(
                        "Redis disconnected - retrying in %.0fs", backoff, exc_info=exc
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _BACKOFF_CAP)
                    _log.info("Attempting to reconnect to Redis outcome listener")
        except asyncio.CancelledError:
            _log.info("OutcomeIntegrationWorker stopped")
            raise
