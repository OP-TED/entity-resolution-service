"""Unit tests for the conditional on_outcome_stored callback wiring.

The callback must call waiter.notify() first and only publish to Redis
Pub/Sub when the local waiter has no event for the triad key — i.e. the
request originated from a different ERS instance.
"""
from unittest.mock import AsyncMock

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
