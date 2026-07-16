# Task 6.2 — AsyncResolutionWaiter

## Goal

Implement the in-process coordination primitive that bridges two asynchronous flows:
`ResolutionCoordinatorService` (waiter side) and the EPIC-05 callback (signaller side).

This component has NO business logic. It is a pure concurrency utility.

---

## Role in the Full Flow

```
resolve_single coroutine                EPIC-05 OutcomeIntegrationService
─────────────────────────────           ─────────────────────────────────
get_or_create(triad_key)  ──creates──►  asyncio.Event (shared)
await asyncio.wait_for(
  event.wait(), timeout=T)              ... ERE outcome written to Decision Store ...
                                        notify(triad_key)  ──sets──► event.set()
◄── event fires, unblocked ────────────
finally: release(triad_key)
```

`AsyncResolutionWaiter` is **per-mention**. It knows nothing about bulk vs single resolution.
Bulk coordination is done at the `asyncio.gather` level in `resolve_bulk` (Task 6.3).

Multiple concurrent `resolve_single` coroutines for the **same triad** (idempotent replay
with no existing decision) share one Event — all are unblocked by a single `notify`.

---

## Scope

### What to build

File: `src/ers/resolution_coordinator/services/async_resolution_waiter.py`

```python
class AsyncResolutionWaiter:

    def __init__(self) -> None:
        self._events: WeakValueDictionary[str, asyncio.Event] = WeakValueDictionary()

    async def get_or_create(self, triad_key: str) -> asyncio.Event: ...
    async def notify(self, triad_key: str) -> None: ...
    async def release(self, triad_key: str) -> None: ...
```

`triad_key` format: `f"{source_id}{request_id}{entity_type}"` — direct concatenation,
no separator. Consistent with `derive_provisional_cluster_id` in
`ers.resolution_decision_store.adapters.provisional_id`.

### What NOT to build
- No timeout logic — timeouts live in the callers (`asyncio.wait_for` in `resolve_single`)
- No business logic, no logging, no OTel spans
- No public module-level function wrapper
- No Redis, Celery, or any external broker
- No `asyncio.Lock` (see Design Rationale below)
- No manual reference counting (see Design Rationale below)

---

## Design Rationale

### Why no `asyncio.Lock`

A previous version of this spec included `asyncio.Lock` on all three methods. This was
removed after analysis:

asyncio is **single-threaded**. Coroutines interleave **only at `await` points**. Every
operation inside the three methods — dict lookup, dict assignment, `event.set()` — is
pure synchronous Python with no `await` between them. Therefore, no two coroutines can
ever interleave inside these critical sections, with or without a lock.

The lock's only effect would be adding an extra `await` on every call, introducing
contention overhead and an extra suspension point — for zero safety benefit.

**The lock was cargo-culted from thread-safe patterns. It does not apply to
single-threaded asyncio.**

### Why `WeakValueDictionary` instead of manual reference counting

A previous version used two dicts (`_events` and `_waiter_counts`) with manual reference
counting in `release` to know when to evict an event.

`weakref.WeakValueDictionary` replaces this entirely:

- Each caller of `get_or_create` receives a strong reference to the `asyncio.Event`
  and holds it as a local variable until its coroutine finishes.
- As long as at least one coroutine holds that local reference, the event stays in
  the `WeakValueDictionary` automatically.
- When the last coroutine releases its local reference (end of `finally` block), CPython's
  reference-counting GC immediately removes the entry from the dict — no explicit eviction needed.
- `notify` on a key whose all waiters have already released is a natural no-op: the key
  is no longer in the dict.

**Result:** `release` becomes a no-op. The two-dict design collapses to one dict. No
counting, no bookkeeping.

**CPython assumption:** `WeakValueDictionary` cleanup is immediate under CPython's
reference-counting GC. This is acceptable for an MVP service. If the service ever runs
under PyPy or GraalPy, this assumption must be revisited.

---

## Asyncio Correctness Requirements

**`get_or_create(triad_key) → asyncio.Event`**

Check the `WeakValueDictionary`. If the key is absent (or the value has been GC'd),
create a new `asyncio.Event`, store it, and return it. The caller holds a strong reference,
keeping the event alive for the duration of its wait.

```python
async def get_or_create(self, triad_key: str) -> asyncio.Event:
    event = self._events.get(triad_key)
    if event is None:
        event = asyncio.Event()
        self._events[triad_key] = event
    return event
```

**`notify(triad_key) → None`**

Look up the key. If present (at least one waiter is still alive), call `event.set()`.
If absent (all waiters timed out and released): no-op.

```python
async def notify(self, triad_key: str) -> None:
    event = self._events.get(triad_key)
    if event is not None:
        event.set()
```

**`release(triad_key) → None`**

No-op. The `WeakValueDictionary` evicts the entry automatically when the caller drops
its strong reference. This method exists to satisfy the integration contract with T6.3
(which calls `release` in a `finally` block) and to make the lifecycle explicit to callers.

```python
async def release(self, triad_key: str) -> None:
    pass
```

---

## pytest-asyncio Setup

`asyncio_mode = auto` in `pytest.ini` — no `@pytest.mark.asyncio` decorator needed on
test functions. Confirmed from project configuration.

---

## Files to Create / Modify

| Action | File |
|--------|------|
| Create | `src/ers/resolution_coordinator/services/async_resolution_waiter.py` |
| Create | `tests/unit/resolution_coordinator/services/__init__.py` |
| Create | `tests/unit/resolution_coordinator/services/test_async_resolution_waiter.py` |

---

## Unit Tests

All tests are `async`. `asyncio_mode = auto` — no decorator needed.

| Test | Scenario |
|------|----------|
| `test_get_or_create_new_key` | New key → Event created and returned |
| `test_get_or_create_same_key_returns_same_event` | Same key twice → identical Event object |
| `test_notify_sets_event` | `notify` on existing key → `event.is_set()` is True |
| `test_notify_unknown_key_is_noop` | `notify` on absent key → no exception, no side effect |
| `test_release_is_noop` | `release` on any key → no exception, no state change |
| `test_event_removed_after_last_ref_dropped` | After all local refs dropped → key absent from internal dict |
| `test_release_unknown_key_is_noop` | Release on absent key → no exception |
| `test_concurrent_get_or_create` | 10 coroutines call `get_or_create` on same key via `asyncio.gather` → all get same Event object |
| `test_notify_unblocks_all_waiters` | 3 coroutines await the same Event; `notify` → all 3 unblock |
| `test_notify_after_all_released_is_noop` | All waiters release, then `notify` → no error |
| `test_late_notify_after_timeout` | Waiter times out, releases, then `notify` called → no error |

Reference implementation for `test_notify_unblocks_all_waiters`:

```python
async def test_notify_unblocks_all_waiters():
    waiter = AsyncResolutionWaiter()
    key = "src1req1Org"
    unblocked = []

    async def wait_and_record():
        event = await waiter.get_or_create(key)
        await asyncio.wait_for(event.wait(), timeout=1.0)
        unblocked.append(True)
        await waiter.release(key)

    tasks = [asyncio.create_task(wait_and_record()) for _ in range(3)]
    await asyncio.sleep(0)          # yield so all tasks start and block on event.wait()
    await waiter.notify(key)
    await asyncio.gather(*tasks)
    assert len(unblocked) == 3
```

Reference for `test_late_notify_after_timeout`:
```python
async def test_late_notify_after_timeout():
    waiter = AsyncResolutionWaiter()
    key = "srcXreqXOrg"
    event = await waiter.get_or_create(key)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(event.wait(), timeout=0.01)
    await waiter.release(key)
    del event                       # drop last strong ref → WeakValueDict evicts entry
    await waiter.notify(key)        # must not raise
```

Note: `test_event_removed_after_last_ref_dropped` must explicitly `del` the local
`event` variable to trigger GC eviction, then assert the key is absent from
`waiter._events`.

---

## Definition of Done

- [ ] All unit tests pass: `poetry run pytest tests/unit/resolution_coordinator/services/test_async_resolution_waiter.py -v`
- [ ] `asyncio_mode = auto` confirmed and documented in test file header comment
- [ ] No test uses `threading.Lock`, `time.sleep`, or real timeouts > 1s
- [ ] `AsyncResolutionWaiter` imports nothing from `ers.resolution_coordinator.domain`
  or any business-logic module
- [ ] `poetry run pylint src/ers/resolution_coordinator/services/async_resolution_waiter.py` — no errors
