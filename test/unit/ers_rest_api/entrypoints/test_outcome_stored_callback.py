"""Unit tests for the conditional on_outcome_stored callback wiring.

The callback must call waiter.notify() first and only publish to Redis
Pub/Sub when the local waiter has no event for the triad key — i.e. the
request originated from a different ERS instance.
"""
import logging
from unittest.mock import AsyncMock

import pytest

from ers.ers_rest_api.entrypoints.api.app import make_outcome_stored_callback

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
