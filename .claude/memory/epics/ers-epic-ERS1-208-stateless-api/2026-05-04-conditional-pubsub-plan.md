# Enhancement Plan: Conditional Pub/Sub Publishing

**Date:** 2026-05-04
**Branch:** feature/ERS1-208/make-ers-stateless (or a follow-on branch)
**Status:** Planned

## Goal

Eliminate unnecessary Redis Pub/Sub traffic by only calling `publish_notification`
when the BRPOP winner does not hold a local event for the resolved triad. This makes
single-instance deployments Pub/Sub-free and removes the conceptual error of using
a cross-process primitive for in-process signaling.

## Scope — files to touch

### Production
| File | Change |
|------|--------|
| `src/ers/resolution_coordinator/services/async_resolution_waiter.py` | `notify()` returns `bool` |
| `src/ers/resolution_coordinator/entrypoints/notification_subscriber_worker.py` | `TriadNotifier` protocol annotation updated |
| `src/ers/ers_rest_api/entrypoints/api/app.py` | `on_outcome_stored` becomes conditional async fn |

### Tests
| File | Change |
|------|--------|
| `test/unit/resolution_coordinator/services/test_async_resolution_waiter.py` | Assert return values on all `notify()` calls |
| `test/unit/resolution_coordinator/entrypoints/test_notification_subscriber_worker.py` | Subscriber ignores return value — no change needed, but verify |
| `test/feature/resolution_coordinator/test_async_resolution_waiter.py` | BDD steps: check return value assertions if any |
| New unit tests in `test/unit/ers_rest_api/` (or closest home) | Verify conditional publish behavior in wiring |

## Implementation steps (TDD order)

### Step 1 — Update `notify()` unit tests (red)

In `test/unit/resolution_coordinator/services/test_async_resolution_waiter.py`,
update existing tests and add two new assertions:

- `test_notify_sets_event` → assert return value is `True`
- `test_notify_unknown_key_is_noop` → assert return value is `False`
- `test_notify_unblocks_all_waiters` → assert return value is `True`
- `test_notify_after_all_released_is_noop` → assert return value is `False`
  (event was GC-evicted; key no longer in WeakValueDictionary)
- `test_late_notify_after_timeout` → assert return value is `False`

Run suite — these tests fail (notify still returns None).

### Step 2 — Update `AsyncResolutionWaiter.notify()` (green)

```python
async def notify(self, triad_key: str) -> bool:
    """Signal all waiters for this triad that an ERE outcome is available.
    ...
    Returns:
        True if a local event was found and set; False if the key is
        unknown (no waiter on this instance owns this triad).
    """
    event = self._events.get(triad_key)
    if event is not None:
        event.set()
        return True
    return False
```

Run suite — Step 1 tests pass.

### Step 3 — Update `TriadNotifier` protocol

In `notification_subscriber_worker.py`:

```python
class TriadNotifier(Protocol):
    async def notify(self, triad_key: str) -> bool: ...
```

The subscriber itself calls `await self._waiter.notify(triad_key)` without using
the return value — no other change needed there.

### Step 4 — Write tests for conditional wiring (red)

Add unit tests (likely in a new `test/unit/ers_rest_api/test_app_wiring.py` or
inline in an existing app test) that verify:

- **Same-instance case:** when `waiter.notify(key)` returns `True`,
  `ere_client.publish_notification` is NOT called.
- **Cross-instance case:** when `waiter.notify(key)` returns `False`,
  `ere_client.publish_notification` IS called with the correct channel and key.

Both tests inject a mock waiter and a mock ere_client into the
`on_outcome_stored` callback and assert call counts.

### Step 5 — Update `app.py` wiring (green)

Replace the lambda:

```python
# Before
on_outcome_stored=lambda key: ere_client.publish_notification(notifications_channel, key),
```

With a named async function defined inside the lifespan:

```python
# After
async def _on_outcome_stored(key: str) -> None:
    if not await waiter.notify(key):
        await ere_client.publish_notification(notifications_channel, key)

outcome_service = OutcomeIntegrationService(
    ...
    on_outcome_stored=_on_outcome_stored,
)
```

Run suite — Step 4 tests pass.

### Step 6 — Full suite

```bash
make -f Makefile.dev test
```

All green. The subscriber worker and integration tests remain unchanged —
cross-instance Pub/Sub paths still exercise `publish_notification` via the
`False` branch.

## What does NOT change

- `OutcomeIntegrationService` — interface unchanged; only the injected callback changes.
- `NotificationSubscriberWorker` — still starts unconditionally; still needed for
  cross-instance notification.
- Integration and BDD tests for the subscriber worker — they mock the waiter with
  `AsyncMock` whose `notify()` already returns a falsy MagicMock, so `publish`
  will still be called in those scenarios. Verify this holds.
- `ResolutionCoordinatorService` — unchanged.

## Key invariant to preserve

`waiter.notify()` must be called BEFORE `publish_notification`. If the order is
reversed, a window opens where the Pub/Sub message arrives on the originating
instance before the local event is set — it would be a no-op, and the subsequent
direct notify would still set the event, so correctness is preserved either way.
But calling local first is the logically correct order and avoids any confusion.
