"""Unit tests for AsyncResolutionWaiter.

asyncio_mode = auto (pytest.ini) — no @pytest.mark.asyncio decorator needed.
"""

import asyncio

import pytest

from ers.resolution_coordinator.services.async_resolution_waiter import AsyncResolutionWaiter

KEY = "src1req1Org"
OTHER_KEY = "src2req2Person"


class TestGetOrCreate:
    async def test_new_key_returns_event(self):
        waiter = AsyncResolutionWaiter()
        event = await waiter.get_or_create(KEY)
        assert isinstance(event, asyncio.Event)

    async def test_same_key_returns_same_event(self):
        waiter = AsyncResolutionWaiter()
        event_a = await waiter.get_or_create(KEY)
        event_b = await waiter.get_or_create(KEY)
        assert event_a is event_b

    async def test_different_keys_return_different_events(self):
        waiter = AsyncResolutionWaiter()
        event_a = await waiter.get_or_create(KEY)
        event_b = await waiter.get_or_create(OTHER_KEY)
        assert event_a is not event_b

    async def test_concurrent_get_or_create_same_key(self):
        waiter = AsyncResolutionWaiter()
        events = await asyncio.gather(*[waiter.get_or_create(KEY) for _ in range(10)])
        first = events[0]
        assert all(e is first for e in events)


class TestNotify:
    async def test_notify_sets_event(self):
        waiter = AsyncResolutionWaiter()
        event = await waiter.get_or_create(KEY)
        await waiter.notify(KEY)
        assert event.is_set()

    async def test_notify_unknown_key_is_noop(self):
        waiter = AsyncResolutionWaiter()
        await waiter.notify("nonexistent-key")  # must not raise

    async def test_notify_unblocks_all_waiters(self):
        waiter = AsyncResolutionWaiter()
        unblocked = []

        async def wait_and_record():
            event = await waiter.get_or_create(KEY)
            await asyncio.wait_for(event.wait(), timeout=1.0)
            unblocked.append(True)
            await waiter.release(KEY)

        tasks = [asyncio.create_task(wait_and_record()) for _ in range(3)]
        await asyncio.sleep(0)  # yield so all tasks start and block on event.wait()
        await waiter.notify(KEY)
        await asyncio.gather(*tasks)
        assert len(unblocked) == 3

    async def test_notify_after_all_released_is_noop(self):
        waiter = AsyncResolutionWaiter()
        event = await waiter.get_or_create(KEY)
        await waiter.release(KEY)
        del event  # drop last strong ref → WeakValueDict evicts entry
        await waiter.notify(KEY)  # must not raise


class TestRelease:
    async def test_release_is_noop(self):
        waiter = AsyncResolutionWaiter()
        await waiter.get_or_create(KEY)
        await waiter.release(KEY)  # must not raise

    async def test_release_unknown_key_is_noop(self):
        waiter = AsyncResolutionWaiter()
        await waiter.release("nonexistent-key")  # must not raise


class TestWeakRefCleanup:
    async def test_event_removed_after_last_ref_dropped(self):
        waiter = AsyncResolutionWaiter()
        event = await waiter.get_or_create(KEY)
        assert KEY in waiter._events
        await waiter.release(KEY)
        del event  # drop last strong ref → CPython GC evicts immediately
        assert KEY not in waiter._events

    async def test_late_notify_after_timeout(self):
        waiter = AsyncResolutionWaiter()
        event = await waiter.get_or_create(KEY)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(event.wait()), timeout=0.01)
        await waiter.release(KEY)
        del event  # drop last strong ref → WeakValueDict evicts entry
        await waiter.notify(KEY)  # must not raise
