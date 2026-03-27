"""Unit tests for OutcomeIntegrationWorker — covers UT-006."""
import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from erspec.models.core import ClusterReference, EntityMentionIdentifier
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
    return EntityMentionResolutionResponse(
        ere_request_id="req:001",
        entity_mention_id=EntityMentionIdentifier(
            source_id="S", request_id="R", entity_type="T"
        ),
        candidates=[ClusterReference(cluster_id="c", confidence_score=0.9, similarity_score=0.8)],
        timestamp=datetime.now(UTC),
    )


async def one_shot_generator(message):
    yield message


async def two_message_generator(m1, m2):
    yield m1
    yield m2


class TestOutcomeIntegrationWorker:
    async def test_run_processes_message(self):
        """Worker calls integrate_outcome for each message from listener."""
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
        m1, m2 = make_response(), make_response()
        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.return_value = two_message_generator(m1, m2)
        service = create_autospec(OutcomeIntegrationService, instance=True)
        service.integrate_outcome = AsyncMock(
            side_effect=[OutcomeValidationError("bad"), None]
        )

        worker = OutcomeIntegrationWorker(listener=listener, service=service)
        await worker.run()

        assert service.integrate_outcome.call_count == 2

    async def test_run_continues_after_triad_not_found(self):
        """UT-006: TriadNotFoundError is caught; loop processes next message."""
        m1, m2 = make_response(), make_response()
        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.return_value = two_message_generator(m1, m2)
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
        m1, m2 = make_response(), make_response()
        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.return_value = two_message_generator(m1, m2)
        service = create_autospec(OutcomeIntegrationService, instance=True)
        service.integrate_outcome = AsyncMock(
            side_effect=[RuntimeError("boom"), None]
        )

        worker = OutcomeIntegrationWorker(listener=listener, service=service)
        await worker.run()

        assert service.integrate_outcome.call_count == 2

    async def test_start_returns_asyncio_task(self):
        """start() returns a running asyncio.Task."""
        async def noop_gen():
            return
            yield  # make it an async generator

        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.return_value = noop_gen()
        service = create_autospec(OutcomeIntegrationService, instance=True)

        worker = OutcomeIntegrationWorker(listener=listener, service=service)
        task = worker.start()
        assert isinstance(task, asyncio.Task)
        await worker.stop()

    async def test_stop_cancels_task_cleanly(self):
        """stop() cancels the background task without raising."""
        async def infinite():
            while True:
                await asyncio.sleep(1)
                yield  # never

        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.return_value = infinite()
        service = create_autospec(OutcomeIntegrationService, instance=True)

        worker = OutcomeIntegrationWorker(listener=listener, service=service)
        worker.start()
        await worker.stop()  # must not hang or raise
