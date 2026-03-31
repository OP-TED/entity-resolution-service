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
        self._events: dict[str, asyncio.Event] = {}
        self._waiter_counts: dict[str, int] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

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

---

## Asyncio Correctness Requirements

**`get_or_create(triad_key) → asyncio.Event`**

Acquires `self._lock` for the entire read-check-write sequence to prevent a race where
two coroutines both see "key absent" and each create a separate Event:

```python
async with self._lock:
    if triad_key not in self._events:
        self._events[triad_key] = asyncio.Event()
        self._waiter_counts[triad_key] = 1
    else:
        self._waiter_counts[triad_key] += 1
    return self._events[triad_key]
```

**`notify(triad_key) → None`**

Acquires `self._lock`, looks up the Event, calls `event.set()` while still holding the
lock. `asyncio.Event.set()` is not a coroutine — it is safe to call under `asyncio.Lock`.

Holding the lock during `set()` prevents a race where `release` removes the Event between
the dict lookup and the `set()` call.

If `triad_key` is not in `_events`: no-op. This is a valid late signal after all waiters
have already released (e.g., all timed out).

```python
async with self._lock:
    event = self._events.get(triad_key)
    if event is not None:
        event.set()
```

**`release(triad_key) → None`**

Acquires `self._lock`, decrements `_waiter_counts[triad_key]`. When count reaches 0,
removes both the Event and the count entry. If key is absent: no-op (defensive).

```python
async with self._lock:
    if triad_key not in self._waiter_counts:
        return
    self._waiter_counts[triad_key] -= 1
    if self._waiter_counts[triad_key] == 0:
        del self._events[triad_key]
        del self._waiter_counts[triad_key]
```

**Why asyncio.Lock (not threading.Lock):**
All callers are coroutines in the same event loop. `asyncio.Lock` releases the event
loop between `acquire` and continuation — `threading.Lock` would deadlock in async code.

**asyncio.Event vs manual flags:**
`asyncio.Event` is the stdlib primitive designed exactly for this pattern. Do not
reimplement with `asyncio.Condition` or `asyncio.Queue` — they add unnecessary complexity.
`event.wait()` suspends the coroutine without blocking the event loop.

---

## pytest-asyncio Setup Check

Before writing tests, verify the project's asyncio test configuration:

1. Check `pyproject.toml` for `asyncio_mode` under `[tool.pytest.ini_options]`.
   - If `asyncio_mode = "auto"` → no decorator needed on test functions
   - If absent or `"strict"` → add `@pytest.mark.asyncio` to each async test
2. Check that `pytest-asyncio` is in `[tool.poetry.dev-dependencies]` or `[tool.poetry.group.test]`.
   If absent, add it and run `poetry lock --no-update && poetry install`.
3. Document which mode is in use as a comment at the top of the test file.

---

## Files to Create / Modify

| Action | File |
|--------|------|
| Create | `src/ers/resolution_coordinator/services/async_resolution_waiter.py` |
| Create | `tests/unit/resolution_coordinator/services/__init__.py` |
| Create | `tests/unit/resolution_coordinator/services/test_async_resolution_waiter.py` |

---

## Unit Tests

All tests are `async`. Cover:

| Test | Scenario |
|------|----------|
| `test_get_or_create_new_key` | New key → Event created, count = 1 |
| `test_get_or_create_same_key_returns_same_event` | Same key twice → identical Event object, count = 2 |
| `test_notify_sets_event` | `notify` on existing key → `event.is_set()` is True |
| `test_notify_unknown_key_is_noop` | `notify` on absent key → no exception, no side effect |
| `test_release_decrements_count` | 2 waiters, 1 releases → Event still in dict, count = 1 |
| `test_release_last_waiter_removes_event` | 1 waiter releases → Event removed from internal dict |
| `test_release_unknown_key_is_noop` | Release on absent key → no exception |
| `test_concurrent_get_or_create` | 10 coroutines call `get_or_create` on same key via `asyncio.gather` → all get same Event object, count = 10 |
| `test_notify_unblocks_all_waiters` | 3 coroutines await the same Event; `notify` → all 3 unblock |
| `test_notify_after_all_released_is_noop` | All waiters release, then `notify` → no error |
| `test_late_notify_after_timeout` | Waiter times out (asyncio.wait_for), then `notify` called → no error, Event already cleaned up |

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
    # After release, notify is a no-op
    await waiter.notify(key)   # must not raise
```

---

## Definition of Done

- [ ] All unit tests pass: `poetry run pytest tests/unit/resolution_coordinator/services/test_async_resolution_waiter.py -v`
- [ ] `asyncio_mode` setting verified and documented in test file header comment
- [ ] No test uses `threading.Lock`, `time.sleep`, or real timeouts > 1s
- [ ] `AsyncResolutionWaiter` imports nothing from `ers.resolution_coordinator.domain`
  or any business-logic module
- [ ] `poetry run pylint src/ers/resolution_coordinator/services/async_resolution_waiter.py` — no errors
