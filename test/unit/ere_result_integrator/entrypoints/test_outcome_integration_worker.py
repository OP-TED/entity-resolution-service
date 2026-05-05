"""Unit tests for OutcomeIntegrationWorker — covers UT-006."""
import asyncio
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

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

    async def test_run_restarts_after_connection_error_from_listener(self):
        """Gap A: ConnectionError from listener triggers restart; next batch processes."""
        message = make_response()
        call_count = 0

        async def first_fails_then_yields():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Redis down")
            yield message

        listener = MagicMock(spec=AsyncOutcomeListener)
        # side_effect (callable) is used here rather than return_value so that each
        # call to consume() produces a fresh generator object. return_value would
        # return the same exhausted generator on the second call (after restart).
        listener.consume.side_effect = first_fails_then_yields
        service = create_autospec(OutcomeIntegrationService, instance=True)
        service.integrate_outcome = AsyncMock(return_value=None)

        with patch("asyncio.sleep", new=AsyncMock()):
            worker = OutcomeIntegrationWorker(listener=listener, service=service)
            await worker.run()

        service.integrate_outcome.assert_called_once_with(message)

    async def test_run_continues_after_connection_error_in_service(self):
        """Gap E: ConnectionError from integrate_outcome is caught; next message processes."""
        m1, m2 = make_response(), make_response()
        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.return_value = two_message_generator(m1, m2)
        service = create_autospec(OutcomeIntegrationService, instance=True)
        service.integrate_outcome = AsyncMock(
            side_effect=[ConnectionError("DB down"), None]
        )

        worker = OutcomeIntegrationWorker(listener=listener, service=service)
        await worker.run()

        assert service.integrate_outcome.call_count == 2

    async def test_infrastructure_connection_error_logged_distinctly(self, caplog):
        """Gap E: ConnectionError from service produces an infrastructure-specific log."""
        message = make_response()
        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.return_value = one_shot_generator(message)
        service = create_autospec(OutcomeIntegrationService, instance=True)
        service.integrate_outcome = AsyncMock(side_effect=ConnectionError("DB down"))

        worker = OutcomeIntegrationWorker(listener=listener, service=service)
        with caplog.at_level(logging.ERROR, logger="ers.ere_result_integrator"):
            await worker.run()

        assert any("infrastructure" in r.message.lower() for r in caplog.records)

    async def test_run_uses_exponential_backoff_on_consecutive_connection_errors(self):
        """Consecutive ConnectionErrors double the sleep duration (1s -> 2s)."""
        call_count = 0

        async def fails_twice_then_yields():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ConnectionError("Redis down")
            yield make_response()

        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.side_effect = fails_twice_then_yields
        service = create_autospec(OutcomeIntegrationService, instance=True)
        service.integrate_outcome = AsyncMock(return_value=None)

        sleep_calls = []

        async def record_sleep(duration):
            sleep_calls.append(duration)

        with patch("asyncio.sleep", new=record_sleep):
            worker = OutcomeIntegrationWorker(listener=listener, service=service)
            await worker.run()

        assert sleep_calls == [1.0, 2.0]

    async def test_run_resets_backoff_after_successful_message(self):
        """Backoff resets to 1s once a message is received successfully.

        Scenario across three consume() calls (side_effect):
        - consume() #1: raises ConnectionError at entry
            -> sleep(1.0), backoff becomes 2.0
        - consume() #2: yields one message (backoff resets to 1.0), then raises
          ConnectionError mid-iteration (propagates to outer try/except)
            -> sleep(1.0)  (NOT 2.0 -- confirms reset)
        - consume() #3: yields one message then exhausts -> break

        Both sleeps must be 1.0, confirming the backoff was reset after the
        first successful message receive.
        """
        call_count = 0
        msg = make_response()

        async def fail_succeed_fail_succeed():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("down")
            if call_count == 2:
                yield msg                        # success - backoff resets to 1.0
                raise ConnectionError("down again")  # mid-iteration error -> outer except
            # call_count >= 3: yield then exhaust -> break
            yield msg

        listener = MagicMock(spec=AsyncOutcomeListener)
        listener.consume.side_effect = fail_succeed_fail_succeed
        service = create_autospec(OutcomeIntegrationService, instance=True)
        service.integrate_outcome = AsyncMock(return_value=None)

        sleep_calls = []

        async def record_sleep(duration):
            sleep_calls.append(duration)

        with patch("asyncio.sleep", new=record_sleep):
            worker = OutcomeIntegrationWorker(listener=listener, service=service)
            await worker.run()

        # Both sleeps must be 1.0: the second failure sleeps 1.0 (not 2.0),
        # confirming the backoff was reset after the successful message in call #2.
        # Note: the mid-iteration raise in call #2 is intentional — a clean exhaust
        # would trigger `break` and exit the loop before reaching the third call.
        assert sleep_calls == [1.0, 1.0]
        assert service.integrate_outcome.call_count == 2  # confirms two successful receives
