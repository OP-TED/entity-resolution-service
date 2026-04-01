"""
Step definitions for: async_resolution_waiter.feature

Feature: Async Resolution Waiter Coordination
  Covers four behaviours:
    1. Waiters unblocked on signal (1 or N waiters, fan-out).
    2. Waiter timeout with event retention for late signals.
    3. Signal with no registered waiters is a no-op.
    4. Event lifecycle on waiter release (partial vs full cleanup).

  These steps operate directly on a real AsyncResolutionWaiter.
  No external services required.
"""

import asyncio
import gc
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from ers.resolution_coordinator.services.async_resolution_waiter import AsyncResolutionWaiter

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE_FILE = str(
    Path(__file__).parent.parent.parent
    / "feature"
    / "resolution_coordinator"
    / "async_resolution_waiter.feature"
)


@scenario(FEATURE_FILE, "Waiters are unblocked when the Result Integrator signals")
def test_waiters_unblocked_on_signal():
    pass


@scenario(FEATURE_FILE, "A waiter is unblocked by timeout when no signal arrives")
def test_waiter_timeout():
    pass


@scenario(FEATURE_FILE, "Signalling a triad with no registered waiters is a no-op")
def test_signal_no_waiters():
    pass


@scenario(FEATURE_FILE, "Event lifecycle on waiter release")
def test_event_lifecycle():
    pass


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _triad_key(source_id: str, request_id: str, entity_type: str = "Organization") -> str:
    return f"{source_id}{request_id}{entity_type}"


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("the async resolution waiter is available")
def waiter_available(ctx):
    ctx["waiter"] = AsyncResolutionWaiter()


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        "{waiter_count:d} waiters are registered for correlation triad "
        '("{source_id}", "{request_id}", "Organization")'
    )
)
def register_n_waiters(ctx, waiter_count, source_id, request_id):
    triad_key = _triad_key(source_id, request_id)
    ctx["triad_key"] = triad_key

    async def _register():
        events = []
        for _ in range(waiter_count):
            e = await ctx["waiter"].get_or_create(triad_key)
            events.append(e)
        return events

    ctx["events"] = asyncio.run(_register())
    ctx["waiter_count"] = waiter_count


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the ERE Result Integrator signals an outcome for that triad")
def signal_outcome(ctx):
    asyncio.run(ctx["waiter"].notify(ctx["triad_key"]))


@when("no signal arrives within the execution window")
def no_signal_timeout(ctx):
    event = ctx["events"][0]

    async def _wait_with_timeout():
        try:
            await asyncio.wait_for(event.wait(), timeout=0.05)
            return False
        except asyncio.TimeoutError:
            return True

    ctx["timed_out"] = asyncio.run(_wait_with_timeout())


@when(
    parsers.parse(
        "the ERE Result Integrator signals an outcome for triad "
        '("{source_id}", "{request_id}", "Organization") with no registered waiters'
    )
)
def signal_no_waiters(ctx, source_id, request_id):
    triad_key = _triad_key(source_id, request_id)
    ctx["triad_key"] = triad_key
    try:
        asyncio.run(ctx["waiter"].notify(triad_key))
        ctx["raised_exception"] = None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ctx["raised_exception"] = exc


@when(parsers.parse("{release_count:d} waiters release"))
def release_n_waiters(ctx, release_count):
    triad_key = ctx["triad_key"]

    async def _release():
        for _ in range(release_count):
            await ctx["waiter"].release(triad_key)

    asyncio.run(_release())
    # Drop strong references so the WeakValueDictionary can evict the entry.
    del ctx["events"][-release_count:]
    gc.collect()


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.parse("all {waiter_count:d} waiters are unblocked"))
def all_n_unblocked(ctx, waiter_count):
    events = ctx["events"][:waiter_count]
    assert all(e.is_set() for e in events), (
        f"Expected {waiter_count} events to be set; "
        f"got {[e.is_set() for e in events]}"
    )


@then("the waiter is unblocked by timeout")
def waiter_unblocked_by_timeout(ctx):
    assert ctx["timed_out"] is True


@then("the event for that triad remains available for a late signal")
def event_remains_available(ctx):
    assert ctx["triad_key"] in ctx["waiter"]._events


@then("no error is raised")
def no_error_raised(ctx):
    assert ctx.get("raised_exception") is None


@then("the event for that triad is still retained")
def event_state_retained(ctx):
    assert ctx["triad_key"] in ctx["waiter"]._events, (
        f"Expected event for {ctx['triad_key']!r} to be retained but it was evicted"
    )


@then("the event for that triad is removed")
def event_state_removed(ctx):
    assert ctx["triad_key"] not in ctx["waiter"]._events, (
        f"Expected event for {ctx['triad_key']!r} to be removed but it is still retained"
    )
