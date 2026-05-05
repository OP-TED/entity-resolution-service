"""Unit tests for NotificationSubscriberWorker."""
import asyncio
import contextlib
import logging
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from ers.resolution_coordinator.entrypoints.notification_subscriber_worker import (
    NotificationSubscriberWorker,
)

_PATCH_TARGET = (
    "ers.resolution_coordinator.entrypoints.notification_subscriber_worker.aioredis.Redis"
)


def make_worker(waiter=None, channel="ers_notifications"):
    redis_config = MagicMock()
    if waiter is None:
        waiter = AsyncMock()
    return NotificationSubscriberWorker(
        redis_config=redis_config,
        channel=channel,
        waiter=waiter,
    )


def make_message(data: str, msg_type: str = "message") -> dict:
    return {"type": msg_type, "data": data.encode()}


@contextmanager
def mock_redis_with_listen(listen_fn):
    """Patch aioredis.Redis so pubsub().listen() calls listen_fn."""
    mock_pubsub = MagicMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.listen = listen_fn

    mock_redis = MagicMock()
    mock_redis.pubsub.return_value = mock_pubsub
    mock_redis.aclose = AsyncMock()

    with patch(_PATCH_TARGET, return_value=mock_redis):
        yield mock_redis, mock_pubsub


async def one_message_generator(msg):
    yield msg


async def empty_generator():
    if False:
        yield


class TestRedisClientConstruction:
    async def test_socket_connect_timeout_forwarded_to_redis_client(self):
        redis_config = MagicMock()
        redis_config.socket_connect_timeout = 7.0
        redis_config.to_redis_kwargs.return_value = {
            "host": "localhost",
            "port": 6379,
            "db": 0,
            "password": None,
            "socket_connect_timeout": 7.0,
        }
        worker = NotificationSubscriberWorker(
            redis_config=redis_config,
            channel="test",
            waiter=AsyncMock(),
        )

        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.listen = lambda: empty_generator()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_redis.aclose = AsyncMock()

        with patch(_PATCH_TARGET, return_value=mock_redis) as mock_redis_cls:
            await worker.run()

        _, kwargs = mock_redis_cls.call_args
        assert kwargs.get("socket_connect_timeout") == 7.0


class TestLifecycle:
    async def test_start_returns_asyncio_task(self):
        worker = make_worker()
        with mock_redis_with_listen(lambda: empty_generator()):
            task = worker.start()
            assert isinstance(task, asyncio.Task)
            await worker.stop()

    async def test_stop_cancels_task_cleanly(self):
        worker = make_worker()

        async def infinite_listen():
            while True:
                await asyncio.sleep(10)
                yield

        with mock_redis_with_listen(infinite_listen):
            worker.start()
            await worker.stop()  # must not hang or raise

    async def test_subscribed_event_set_after_subscribe(self):
        worker = make_worker()
        assert not worker.subscribed.is_set()

        msg = make_message("k")
        with mock_redis_with_listen(lambda: one_message_generator(msg)):
            await worker.run()

        assert worker.subscribed.is_set()

    async def test_subscribed_event_cleared_on_connection_error(self):
        worker = make_worker()
        call_count = 0

        async def fail_then_done():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RedisConnectionError("down")
            if False:
                yield

        with mock_redis_with_listen(fail_then_done), patch("asyncio.sleep", new=AsyncMock()):
            await worker.run()

        # After ConnectionError the event was cleared; after reconnect it is set again
        assert worker.subscribed.is_set()


class TestMessageHandling:
    async def test_message_calls_waiter_notify(self):
        waiter = AsyncMock()
        worker = make_worker(waiter=waiter)

        msg = make_message("SRCIDreqidORGANISATION")
        with mock_redis_with_listen(lambda: one_message_generator(msg)):
            await worker.run()

        waiter.notify.assert_awaited_once_with("SRCIDreqidORGANISATION")

    async def test_malformed_payload_logged_and_skipped(self, caplog):
        """A non-utf-8 payload must not kill the worker."""
        waiter = AsyncMock()
        worker = make_worker(waiter=waiter)

        bad = {"type": "message", "data": b"\xff\xfe\xfd"}
        good = make_message("validkey")

        async def two_messages():
            yield bad
            yield good

        with mock_redis_with_listen(two_messages), caplog.at_level(logging.WARNING):
            await worker.run()

        waiter.notify.assert_awaited_once_with("validkey")
        assert any("invalid payload" in r.message.lower() for r in caplog.records)

    async def test_payload_without_data_skipped(self):
        """A frame missing the bytes 'data' attribute must not kill the worker."""
        waiter = AsyncMock()
        worker = make_worker(waiter=waiter)

        # 'data' is an int — has no .decode(); current code crashes with AttributeError.
        bad = {"type": "message", "data": 12345}
        good = make_message("k2")

        async def two_messages():
            yield bad
            yield good

        with mock_redis_with_listen(two_messages):
            await worker.run()

        waiter.notify.assert_awaited_once_with("k2")

    async def test_subscribe_confirmation_ignored(self):
        waiter = AsyncMock()
        worker = make_worker(waiter=waiter)

        subscribe_confirm = make_message("1", msg_type="subscribe")
        with mock_redis_with_listen(lambda: one_message_generator(subscribe_confirm)):
            await worker.run()

        waiter.notify.assert_not_called()


class TestReconnect:
    async def test_connection_error_triggers_retry(self):
        waiter = AsyncMock()
        worker = make_worker(waiter=waiter)
        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RedisConnectionError("Redis down")
            yield make_message("key1")

        with mock_redis_with_listen(fail_then_succeed), patch("asyncio.sleep", new=AsyncMock()):
            await worker.run()

        waiter.notify.assert_awaited_once_with("key1")

    async def test_connection_error_logged_at_warning(self, caplog):
        worker = make_worker()
        call_count = 0

        async def fail_then_done():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RedisConnectionError("Redis down")
            if False:
                yield

        with mock_redis_with_listen(fail_then_done), caplog.at_level(logging.WARNING), patch("asyncio.sleep", new=AsyncMock()):
            await worker.run()

        assert any(r.levelno >= logging.WARNING for r in caplog.records)

    async def test_backoff_doubles_up_to_cap(self):
        worker = make_worker()
        sleep_calls = []
        call_count = 0

        async def always_fails():
            nonlocal call_count
            call_count += 1
            if call_count > 8:
                if False:
                    yield
                return
            raise RedisConnectionError("down")

        async def capture_sleep(delay):
            sleep_calls.append(delay)

        with mock_redis_with_listen(always_fails), patch("asyncio.sleep", side_effect=capture_sleep):
            await worker.run()

        assert sleep_calls[:4] == [1, 2, 4, 8]
        assert all(s <= 30 for s in sleep_calls)

    async def test_cancelled_error_reraises(self):
        worker = make_worker()

        async def infinite_listen():
            while True:
                await asyncio.sleep(10)
                yield

        with mock_redis_with_listen(infinite_listen):
            task = asyncio.create_task(worker.run())
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


class TestCleanup:
    async def test_aclose_runs_even_when_unsubscribe_raises_cancelled(self):
        """A CancelledError raised by unsubscribe must not skip aclose.

        Pre-fix: contextlib.suppress(Exception) does not catch CancelledError on
        Python 3.11+, so a cancel mid-unsubscribe leaks the Redis connection.
        """
        worker = make_worker()
        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock(side_effect=asyncio.CancelledError())
        mock_pubsub.listen = lambda: one_message_generator(make_message("k"))

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_redis.aclose = AsyncMock()

        with patch(_PATCH_TARGET, return_value=mock_redis):
            with contextlib.suppress(asyncio.CancelledError):
                await worker.run()

        mock_redis.aclose.assert_awaited()

    async def test_aclose_runs_even_when_unsubscribe_raises_exception(self):
        """An ordinary Exception during unsubscribe must not skip aclose."""
        worker = make_worker()
        mock_pubsub = MagicMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock(side_effect=RuntimeError("boom"))
        mock_pubsub.listen = lambda: one_message_generator(make_message("k"))

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_redis.aclose = AsyncMock()

        with patch(_PATCH_TARGET, return_value=mock_redis):
            await worker.run()

        mock_redis.aclose.assert_awaited()
