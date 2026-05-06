"""Integration tests for NotificationSubscriberWorker against a real Redis instance."""
import asyncio

import pytest
import redis.asyncio as aioredis

from ers.commons.adapters.redis_client import RedisConnectionConfig
from ers.resolution_coordinator.entrypoints.notification_subscriber_worker import (
    NotificationSubscriberWorker,
)

CHANNEL = "ers_notifications_test"


@pytest.fixture
def redis_connection_config(redis_container) -> RedisConnectionConfig:
    return RedisConnectionConfig(
        host=redis_container.get_container_host_ip(),
        port=int(redis_container.get_exposed_port(6379)),
        db=0,
    )


class TestNotificationRoundTrip:
    async def test_publish_triggers_waiter_notify(
        self,
        redis_client: aioredis.Redis,
        redis_connection_config: RedisConnectionConfig,
    ):
        """Publishing to the channel reaches waiter.notify with the correct triad_key."""
        received_keys = []
        done = asyncio.Event()

        class _Waiter:
            async def notify(self, key):
                received_keys.append(key)
                done.set()

        worker = NotificationSubscriberWorker(
            redis_config=redis_connection_config,
            channel=CHANNEL,
            waiter=_Waiter(),
        )
        worker.start()
        await asyncio.wait_for(worker.subscribed.wait(), timeout=5.0)

        triad_key = "SRCIDrequestidORGANISATION"
        await redis_client.publish(CHANNEL, triad_key)

        try:
            await asyncio.wait_for(done.wait(), timeout=3.0)
        finally:
            await worker.stop()

        assert received_keys == [triad_key]

    async def test_worker_processes_multiple_messages_in_order(
        self,
        redis_client: aioredis.Redis,
        redis_connection_config: RedisConnectionConfig,
    ):
        """All published messages are delivered to waiter.notify in order."""
        received_keys = []
        done = asyncio.Event()
        expected = ["key1", "key2", "key3"]

        class _Waiter:
            async def notify(self, key):
                received_keys.append(key)
                if len(received_keys) == len(expected):
                    done.set()

        worker = NotificationSubscriberWorker(
            redis_config=redis_connection_config,
            channel=CHANNEL,
            waiter=_Waiter(),
        )
        worker.start()
        await asyncio.wait_for(worker.subscribed.wait(), timeout=5.0)

        for k in expected:
            await redis_client.publish(CHANNEL, k)

        try:
            await asyncio.wait_for(done.wait(), timeout=3.0)
        finally:
            await worker.stop()

        assert received_keys == expected
