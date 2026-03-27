---
name: task59-resilience-gaps
description: Fix 5 resilience gaps identified in EPIC-05 post-implementation review
type: project
---

# Task 59 — Resilience Gaps in ERE Result Integrator

Identified during post-implementation review (2026-03-27).
All gaps are in the happy-path code that was not covered by spec UT/IT tests.

---

## Gap Inventory

### 🔴 A — Worker dies silently on Redis connection drop
**File:** `src/ers/ere_result_integrator/adapters/redis_outcome_listener.py:43`
**Root cause:** `await self._client.pull_response()` has no `try/except`. A
`ConnectionError` (or `TimeoutError`) propagates out of the async generator,
exits the `async for` in `worker.run()`, and terminates the background task
silently. No log, no restart, no alert.

**Fix:** Wrap `pull_response()` in a `try/except (ConnectionError, TimeoutError)`
inside the `while True` loop. On `ConnectionError`, log ERROR and re-raise so
the generator exits cleanly (the worker will catch it as `except Exception`).
Alternatively, add reconnect back-off inside the listener — preferred approach:
**let the listener propagate the error** and add a **restart loop** in the worker
(gap F below). Fixing A in isolation without the restart loop only improves
the log message, not the outcome.

**Proposed pattern (listener side):**
```python
while True:
    try:
        response = await self._client.pull_response()
    except (ConnectionError, TimeoutError) as exc:
        _log.error("Redis connection lost in outcome listener", exc_info=exc)
        raise  # exit the async generator; worker loop will catch
    if isinstance(response, EntityMentionResolutionResponse):
        ...
```

**Proposed pattern (worker side — restart loop, gap F):**
```python
while not self._stopping:
    try:
        async for message in self._listener.consume():
            ...
    except (ConnectionError, TimeoutError):
        _log.warning("Redis disconnected - retrying in 5 s")
        await asyncio.sleep(5)
    except asyncio.CancelledError:
        break
```

---

### 🔴 B — Coordinator doorbell raises, caller hangs forever
**File:** `src/ers/ere_result_integrator/services/outcome_integration_service.py:120`
**Root cause:** `await self._on_outcome_stored(triad_key)` has no `try/except`.
If `AsyncResolutionWaiter.notify` raises (e.g., it is shut down or the internal
queue is full), the exception escapes the service and is caught by the worker's
generic `except Exception` — which logs and continues. The Decision Store was
already written at step 5. The coordinator never receives the notification.
Any task waiting on that triad hangs until the provisional timeout expires.

**Fix:** Wrap step 6 in a `try/except Exception` at the **service layer**, log
ERROR with the triad key, and return the already-persisted `decision`. The
Decision Store write is already committed — losing the notification is a degraded
state, not a fatal error.

**Proposed patch (service.py step 6):**
```python
if self._on_outcome_stored is not None:
    triad_key = (
        f"{identifier.source_id}"
        f"{identifier.request_id}"
        f"{identifier.entity_type}"
    )
    try:
        await self._on_outcome_stored(triad_key)
    except Exception as exc:  # noqa: BLE001
        _log.error(
            "Coordinator notification failed - decision persisted but caller may hang",
            exc_info=exc,
            extra={"triad_key": triad_key},
        )
```

---

### 🔴 C — Malformed JSON / unknown type in pull_response() loses message silently
**File:** `src/ers/commons/adapters/redis_client.py` (inside `pull_response()`)
**Root cause:** `get_response_from_message(raw_msg)` is called without a
`try/except`. A `json.JSONDecodeError` or `pydantic.ValidationError` on a
corrupted or schema-evolved message propagates out of `pull_response()`, through
the listener, and into the worker's `except Exception` handler — which logs it
with only the `ere_request_id` from the `message` variable (which was never set,
so this actually causes a `NameError` in the worker's except branch, silently
swallowed by the outer gather).

**Fix:** Two-layer defence:
1. In `redis_client.py`, wrap `get_response_from_message(...)` in
   `try/except (json.JSONDecodeError, ValidationError)`, log ERROR with the raw
   bytes (truncated), and raise a new domain-neutral `MessageDeserializationError`
   (or re-raise as `ValueError`).
2. In the worker, catch `ValueError` / `MessageDeserializationError` before the
   generic `except Exception` so the log message is meaningful.

**Alternative (simpler):** Catch inside `RedisOutcomeListener.consume()` and log
the raw bytes there — keeps the fix local to the listener and avoids adding a
new exception type.

```python
try:
    response = await self._client.pull_response()
except ValueError as exc:
    _log.error("Undeserializable ERE message - discarding", exc_info=exc)
    continue  # skip to next iteration, do not die
```

---

### 🟡 D — Unknown response type silently dropped
**File:** `src/ers/ere_result_integrator/adapters/redis_outcome_listener.py:44-53`
**Root cause:** No `else` branch after `isinstance` checks. A new response type
from a future `erspec` version is silently discarded — no log entry at all.
Version skew between ERS and ERE becomes invisible.

**Fix:** Add an `else` branch that logs WARNING with `type(response).__name__`
and the `ere_request_id` (if present).

```python
else:
    _log.warning(
        "Unrecognised ERE response type - skipping",
        extra={"response_type": type(response).__name__},
    )
```

---

### 🟡 E — Infrastructure errors indistinguishable from business errors in worker
**File:** `src/ers/ere_result_integrator/entrypoints/outcome_integration_worker.py:98`
**File:** `src/ers/ere_result_integrator/services/outcome_integration_service.py:84,96`
**Root cause:** `RepositoryConnectionError` (or any infrastructure exception) from
the registry or decision store is caught by the worker's generic `except Exception`
and logged identically to business errors like `TriadNotFoundError`. There is no
way to tell from the logs whether the failure is retriable (infra) or permanent
(bad message).

**Fix:** Introduce a `RetriableOutcomeError` marker exception (or catch known
infra exceptions by type) in the worker and log them with a distinct message
that makes restart/retry semantics clear.

```python
except (ConnectionError, RepositoryConnectionError) as exc:
    _log.error(
        "Infrastructure error processing outcome - message may be retried on restart",
        exc_info=exc,
        extra={"ere_request_id": message.ere_request_id},
    )
```

---

## Implementation Order

| Priority | Gap | File(s) to Change | Scope |
|----------|-----|-------------------|-------|
| 1 | A + worker restart | `redis_outcome_listener.py`, `outcome_integration_worker.py` | Medium |
| 2 | B | `outcome_integration_service.py` | Small |
| 3 | C | `redis_outcome_listener.py` (or `redis_client.py`) | Small |
| 4 | D | `redis_outcome_listener.py` | Trivial |
| 5 | E | `outcome_integration_worker.py` | Small |

Gaps A+B are critical for production correctness.
Gaps C+D are needed for operational observability.
Gap E is a nice-to-have log clarity improvement.

---

## Tests to Add

Each fix needs at least one unit test:

- **A:** `test_consume_propagates_connection_error` + `test_worker_restarts_after_connection_error`
- **B:** `test_integrate_outcome_logs_callback_error_and_returns_decision`
- **C:** `test_consume_skips_undeserializable_message` (or test in redis_client)
- **D:** `test_consume_logs_unknown_response_type`
- **E:** `test_worker_logs_infrastructure_error_distinctly`

---

**Why:** Post-implementation resilience review — production correctness and
operational observability are non-negotiable for a background worker with no
retry queue. A dead worker would silently stall all async resolutions.

**How to apply:** Pick gaps in priority order. Each is a small, isolated change
with a matching unit test. Do not batch all 5 into one commit.