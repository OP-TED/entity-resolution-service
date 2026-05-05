"""Unit tests for the on_outcome_stored callback wiring and the lifespan
startup gate.

The callback must call waiter.notify() first and only publish to Redis
Pub/Sub when the local waiter has no event for the triad key — i.e. the
request originated from a different ERS instance.

The startup gate awaits the subscriber's SUBSCRIBE handshake before the
HTTP server starts accepting traffic so peers cannot publish into a
not-yet-subscribed pod.
"""
import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from ers.ers_rest_api.entrypoints.api.app import (
    _await_subscriber_ready,
    make_outcome_stored_callback,
)

CHANNEL = "ers_notifications"
KEY = "src1req1Org"


class TestMakeOutcomeStoredCallback:
    async def test_local_event_found_skips_publish(self):
        waiter = AsyncMock()
        waiter.notify.return_value = True
        ere_client = AsyncMock()

        callback = make_outcome_stored_callback(waiter, ere_client, CHANNEL)
        await callback(KEY)

        waiter.notify.assert_awaited_once_with(KEY)
        ere_client.publish_notification.assert_not_called()

    async def test_no_local_event_publishes_to_channel(self):
        waiter = AsyncMock()
        waiter.notify.return_value = False
        ere_client = AsyncMock()

        callback = make_outcome_stored_callback(waiter, ere_client, CHANNEL)
        await callback(KEY)

        waiter.notify.assert_awaited_once_with(KEY)
        ere_client.publish_notification.assert_awaited_once_with(CHANNEL, KEY)

    async def test_publish_failure_logs_warning_and_propagates(self, caplog):
        """When publish raises, the callback logs a warning so operators see
        the cross-instance outage, then lets the exception propagate so the
        upstream OutcomeIntegrationService can record it as well."""
        waiter = AsyncMock()
        waiter.notify.return_value = False
        ere_client = AsyncMock()
        ere_client.publish_notification.side_effect = ConnectionError("redis down")

        callback = make_outcome_stored_callback(waiter, ere_client, CHANNEL)

        with caplog.at_level(logging.WARNING), pytest.raises(ConnectionError):
            await callback(KEY)

        assert any(
            "publish failed" in r.message.lower() and KEY in r.message
            for r in caplog.records
        )


class TestAwaitSubscriberReady:
    """Lifespan startup gate — do not yield to the HTTP server until the
    notification subscriber has finished SUBSCRIBE-ing.
    """

    async def test_returns_when_subscribed_already_set(self):
        worker = AsyncMock()
        worker.subscribed = asyncio.Event()
        worker.subscribed.set()

        await asyncio.wait_for(
            _await_subscriber_ready(worker, timeout=5.0), timeout=0.1
        )

    async def test_waits_then_returns_when_subscribed_set_late(self):
        worker = AsyncMock()
        worker.subscribed = asyncio.Event()

        async def set_after_delay():
            await asyncio.sleep(0.02)
            worker.subscribed.set()

        asyncio.create_task(set_after_delay())
        await _await_subscriber_ready(worker, timeout=5.0)
        assert worker.subscribed.is_set()

    async def test_logs_warning_and_returns_on_timeout(self, caplog):
        """Degraded mode rather than hard fail — the gate is best-effort."""
        worker = AsyncMock()
        worker.subscribed = asyncio.Event()  # never set

        with caplog.at_level(logging.WARNING):
            await _await_subscriber_ready(worker, timeout=0.05)

        assert any(
            "subscriber" in r.message.lower() and "not ready" in r.message.lower()
            for r in caplog.records
        )

    async def test_zero_timeout_skips_wait(self):
        worker = AsyncMock()
        worker.subscribed = asyncio.Event()  # never set

        await asyncio.wait_for(
            _await_subscriber_ready(worker, timeout=0.0), timeout=0.1
        )
