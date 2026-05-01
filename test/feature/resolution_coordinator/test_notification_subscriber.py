"""
Step definitions for: notification_subscriber.feature

Feature: Cross-instance ERE outcome notification
  Tests that publishing to the Redis Pub/Sub channel unblocks the correct waiter
  on any ERS instance, and that a subscriber reconnects after a Redis outage.

All async orchestration runs inside a single asyncio.run() call (in the final
Then step) to avoid cross-event-loop task sharing.
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from ers.commons.adapters.redis_client import RedisConnectionConfig
from ers.resolution_coordinator.entrypoints.notification_subscriber_worker import (
    NotificationSubscriberWorker,
)
from ers.resolution_coordinator.services.async_resolution_waiter import AsyncResolutionWaiter

FEATURE_FILE = str(
    Path(__file__).parent.parent.parent
    / "feature"
    / "resolution_coordinator"
    / "notification_subscriber.feature"
)

_CHANNEL = "ers_notifications_bdd_test"

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE_FILE, "ERE outcome processed by one instance unblocks waiter on another")
def test_cross_instance_notification():
    pass


@scenario(FEATURE_FILE, "Notification lost during subscriber reconnect degrades to timeout")
def test_reconnect_degrades_to_timeout():
    pass


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    return {}


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("the Redis pub/sub infrastructure is available")
def redis_infra_available(ctx, redis_container):
    ctx["redis_container"] = redis_container


# ---------------------------------------------------------------------------
# Scenario 1 steps (async orchestration deferred to the Then step)
# ---------------------------------------------------------------------------


@given("two AsyncResolutionWaiter instances sharing a Redis Pub/Sub channel")
def two_waiter_instances(ctx):
    container = ctx["redis_container"]
    ctx["redis_config"] = RedisConnectionConfig(
        host=container.get_container_host_ip(),
        port=int(container.get_exposed_port(6379)),
        db=0,
    )
    ctx["waiter_a"] = AsyncResolutionWaiter()
    ctx["waiter_b"] = AsyncResolutionWaiter()


@given(parsers.parse('instance A is waiting on triad_key "{triad_key}"'))
def instance_a_waiting(ctx, triad_key):
    ctx["triad_key"] = triad_key


@when(parsers.parse('instance B publishes "{triad_key}" to the notifications channel'))
def instance_b_publishes(ctx, triad_key):
    ctx["publish_key"] = triad_key


@then(parsers.parse("instance A's event is set within {seconds:g} second"))
def event_set_within_timeout(ctx, seconds):
    """Run the full round-trip in one event loop: start subscriber, publish, assert."""
    triad_key = ctx["triad_key"]
    publish_key = ctx["publish_key"]
    waiter_a = ctx["waiter_a"]
    redis_config = ctx["redis_config"]
    container = ctx["redis_container"]

    async def _run():
        import redis.asyncio as aioredis

        worker_a = NotificationSubscriberWorker(
            redis_config=redis_config,
            channel=_CHANNEL,
            waiter=waiter_a,
        )
        worker_a.start()
        await asyncio.wait_for(worker_a.subscribed.wait(), timeout=5.0)

        event = await waiter_a.get_or_create(triad_key)
        ctx["event_a"] = event

        # Publish from a separate client (simulates "instance B" PUBLISH)
        publisher = aioredis.Redis(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(6379)),
        )
        await publisher.publish(_CHANNEL, publish_key)
        await publisher.aclose()

        try:
            await asyncio.wait_for(event.wait(), timeout=seconds)
        finally:
            await worker_a.stop()

    asyncio.run(_run())
    assert ctx["event_a"].is_set()


@then(parsers.parse('instance B\'s waiter has no live event for "{triad_key}"'))
def instance_b_has_no_event(ctx, triad_key):
    assert triad_key not in ctx["waiter_b"]._events


# ---------------------------------------------------------------------------
# Scenario 2 steps
# ---------------------------------------------------------------------------


@given("a NotificationSubscriberWorker is connected to Redis")
def subscriber_worker_connected(ctx):
    ctx["call_count"] = 0
    ctx["received_after_reconnect"] = []


@given(parsers.parse('a waiter is waiting on triad_key "{triad_key}" with a {seconds:g} second timeout'))
def waiter_waiting_with_timeout(ctx, triad_key, seconds):
    ctx["triad_key"] = triad_key
    ctx["timeout"] = seconds


@when("the Redis connection drops before the notification is published")
def connection_drops(ctx):
    received = ctx["received_after_reconnect"]
    call_count_ref = [0]

    from redis.exceptions import ConnectionError as _RedisLibConnectionError

    async def flaky_listen():
        call_count_ref[0] += 1
        if call_count_ref[0] == 1:
            raise _RedisLibConnectionError("Redis down")
        yield {"type": "message", "data": b"recovery_key"}

    mock_pubsub = MagicMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.listen = flaky_listen
    mock_redis = MagicMock()
    mock_redis.pubsub.return_value = mock_pubsub
    mock_redis.aclose = AsyncMock()

    triad_key = ctx["triad_key"]
    timeout = ctx["timeout"]

    real_waiter = AsyncResolutionWaiter()

    class _Waiter:
        async def get_or_create(self, key):
            return await real_waiter.get_or_create(key)

        async def notify(self, key):
            received.append(key)
            await real_waiter.notify(key)

    async def _run():
        waiter = _Waiter()
        event = await real_waiter.get_or_create(triad_key)
        ctx["event"] = event

        worker = NotificationSubscriberWorker(
            redis_config=MagicMock(),
            channel=_CHANNEL,
            waiter=waiter,
        )

        _patch = patch(
            "ers.resolution_coordinator.entrypoints.notification_subscriber_worker.aioredis.Redis",
            return_value=mock_redis,
        )
        with _patch:
            with patch("asyncio.sleep", new=AsyncMock()):
                await worker.run()

        # Check timeout
        try:
            await asyncio.wait_for(asyncio.shield(event.wait()), timeout=timeout)
            ctx["timed_out"] = False
        except TimeoutError:
            ctx["timed_out"] = True

    asyncio.run(_run())


@then("the waiter times out without receiving a signal")
def waiter_times_out(ctx):
    assert ctx["timed_out"], "Expected the waiter to time out but it was signalled"


@then("the worker reconnects and resumes processing subsequent messages")
def worker_resumes(ctx):
    assert "recovery_key" in ctx["received_after_reconnect"]
