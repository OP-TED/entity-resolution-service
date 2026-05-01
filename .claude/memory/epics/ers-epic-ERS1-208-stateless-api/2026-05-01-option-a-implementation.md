# Option A Implementation Spec and Outcome: Redis Pub/Sub Broadcast Notification

**Epic:** ERS1-208 — Make ERS Stateless
**Task:** T2 — Option A implementation
**Outcome:** Fully implemented and all tests green. See §1-8 for spec; all decisions in §9 were applied as specified.
**Fixes:** BLOCKER identified in `2026-05-01-statefulness-audit.md §4`
**Branch:** `feature/ERS1-208/make-ers-stateless`
**Date:** 2026-05-01

---

## 1. Goal

Replace the in-process `waiter.notify()` callback in `OutcomeIntegrationService` with a
Redis Pub/Sub broadcast so that any ERS instance can process the ERE BRPOP response and all
instances are notified, regardless of which one consumed the message.

`AsyncResolutionWaiter` and `ResolutionCoordinatorService` are **not touched**.

---

## 2. What Changes and What Does Not

| Component | Change |
|-----------|--------|
| `OutcomeIntegrationService` | None — interface unchanged; only the injected `on_outcome_stored` value changes in `app.py` |
| `AsyncResolutionWaiter` | None |
| `ResolutionCoordinatorService` | None |
| `OutcomeIntegrationWorker` | None |
| `RedisEREClient` | Add `publish_notification()` method |
| `RedisConfig` (`ers/__init__.py`) | Add `ERS_NOTIFICATIONS_CHANNEL` property |
| `app.py` lifespan | Change `on_outcome_stored` injection + add subscriber worker |
| `dependencies.py` | None |

New files to create:

| File | Purpose |
|------|---------|
| `src/ers/resolution_coordinator/entrypoints/__init__.py` | New package (directory does not yet exist) |
| `src/ers/resolution_coordinator/entrypoints/notification_subscriber_worker.py` | Subscriber background task |

---

## 3. Configuration

Add one property to `RedisConfig` in `src/ers/__init__.py`:

```python
@env_property(default_value="ers_notifications")
def ERS_NOTIFICATIONS_CHANNEL(self, config_value: str) -> str:
    return config_value
```

`ERSConfigResolver` inherits `RedisConfig` so this is immediately available as
`config.ERS_NOTIFICATIONS_CHANNEL` everywhere the singleton is imported.

---

## 4. `RedisEREClient.publish_notification()`

**File:** `src/ers/commons/adapters/redis_client.py`

`PUBLISH` is a regular Redis command — it does not require a dedicated connection and can
share the existing `self._redis_client` with `LPUSH`. No new connection needed on the
publish side.

Add as a new method on `RedisEREClient` only (not on `AbstractClient` — the ABC is scoped
to the ERE request/response contract):

```python
async def publish_notification(self, channel: str, triad_key: str) -> None:
    """Publish triad_key to a Redis Pub/Sub channel.

    Args:
        channel: Redis Pub/Sub channel name (e.g. ``ers_notifications``).
        triad_key: Notification payload — concatenated source_id + request_id + entity_type.

    Raises:
        ConnectionError: If the Redis connection is unavailable.
    """
    try:
        await self._redis_client.publish(channel, triad_key)
    except _RedisLibConnectionError as exc:
        raise ConnectionError(str(exc)) from exc
```

---

## 5. `NotificationSubscriberWorker`

**File:** `src/ers/resolution_coordinator/entrypoints/notification_subscriber_worker.py`

Mirrors the lifecycle pattern of `OutcomeIntegrationWorker`: one asyncio background task,
`start()` / `await stop()`, auto-reconnect loop.

### Constructor

```python
def __init__(
    self,
    redis_config: RedisConnectionConfig,
    channel: str,
    waiter: AsyncResolutionWaiter,
) -> None:
```

The worker creates its own `aioredis.Redis` instance from `redis_config`.
This is a **mandatory** new connection: `SUBSCRIBE` puts a connection into pub/sub mode
where no regular Redis commands can run. Neither `app.state.redis_client` (LPUSH) nor
`listener_client` (BRPOP) can be reused — both would break. The decision in §9 Q2 is
only about *how* this new connection is provisioned (injected config vs. injected client
object), not about whether a new connection is needed.

### Lifecycle

```python
def start(self) -> asyncio.Task: ...   # asyncio.create_task(self.run(), ...)
async def stop(self) -> None: ...      # cancel + gather
```

Same pattern as `OutcomeIntegrationWorker.start()` / `stop()`.

### `run()` loop

`ConnectionError` propagates *out of* `pubsub.listen()` when the socket drops, so the
reconnect loop must wrap the entire `async for`, not sit alongside it:

```
outer loop:
    try:
        connect → pubsub = redis_client.pubsub() → await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue      # skip subscribe-confirmation messages
            triad_key = message["data"].decode()
            await waiter.notify(triad_key)
        break  # listen() exhausted normally (only in tests / graceful shutdown)
    except ConnectionError:
        log WARNING, backoff (exponential, cap 30s), continue outer loop
    except CancelledError:
        log INFO, raise (clean shutdown — propagates out of outer loop)
```

`pubsub.listen()` is a true async generator — it `await`s on the socket and fires
immediately when a message arrives. No polling interval; latency is network RTT only.

### Auto-reconnect backoff

| Attempt | Wait before retry |
|---------|------------------|
| 1 | 1 s |
| 2 | 2 s |
| 3 | 4 s |
| … | doubles each time |
| cap | 30 s |

Log each attempt at `WARNING` level. Log successful reconnect at `INFO`.

---

## 6. `app.py` Lifespan Changes

Two changes inside the existing lifespan function in
`src/ers/ers_rest_api/entrypoints/api/app.py`:

### 6.1 Change `on_outcome_stored` injection

```python
# Before
outcome_service = OutcomeIntegrationService(
    registry_service=registry_service,
    decision_service=decision_service,
    on_outcome_stored=waiter.notify,
)

# After — capture the client and channel as locals before the lambda
notifications_channel = config.ERS_NOTIFICATIONS_CHANNEL
ere_client = ...  # the RedisEREClient already assigned to app.state.redis_client
outcome_service = OutcomeIntegrationService(
    registry_service=registry_service,
    decision_service=decision_service,
    on_outcome_stored=lambda key: ere_client.publish_notification(notifications_channel, key),
)
```

`publish_notification` is `async def`, so the lambda returns a coroutine object.
`OutcomeIntegrationService` does `await self._on_outcome_stored(triad_key)` — this works
without any change to the service.

### 6.2 Add subscriber worker

```python
from ers.resolution_coordinator.entrypoints.notification_subscriber_worker import (
    NotificationSubscriberWorker,
)

# in lifespan startup, after waiter is created:
subscriber_worker = NotificationSubscriberWorker(
    redis_config=RedisConnectionConfig.from_settings(config),
    channel=config.ERS_NOTIFICATIONS_CHANNEL,
    waiter=waiter,
)
subscriber_worker.start()

# in lifespan cleanup (finally block, alongside worker.stop()):
await subscriber_worker.stop()
```

The subscriber worker uses a **dedicated** `aioredis.Redis` connection (created internally).
This is the third Redis connection in the lifespan, alongside:
- `app.state.redis_client` — LPUSH (ERE requests) + PUBLISH (notifications)
- `listener_client` — BRPOP (ERE responses)
- `subscriber_worker` — SUBSCRIBE (notification broadcasts) ← new

---

## 7. Test Plan

### 7.1 Unit tests

**`tests/unit/commons/adapters/test_redis_client.py`** — extend existing file:

| Test | Assertion |
|------|-----------|
| `publish_notification` calls `redis.publish(channel, triad_key)` | Verify args via mock |
| `publish_notification` wraps `_RedisLibConnectionError` as `ConnectionError` | Exception type |

**`tests/unit/resolution_coordinator/entrypoints/test_notification_subscriber_worker.py`** — new file:

| Test | Assertion |
|------|-----------|
| `start()` creates an asyncio Task | Task is not None, not done |
| `stop()` cancels and awaits the task | Task is cancelled |
| `run()` receives message → calls `waiter.notify(triad_key)` | Mock `pubsub.listen()` as async generator yielding one message; assert `waiter.notify` called |
| `run()` ignores subscribe-confirmation messages | Mock `listen()` yielding `{"type": "subscribe", ...}`; assert `waiter.notify` not called |
| `run()` on `ConnectionError` from `listen()` → retries after backoff | Mock `listen()` raising `ConnectionError`; assert reconnect attempted and logged at WARNING |
| `run()` backoff doubles up to 30s cap | Assert sleep durations via mock: 1s, 2s, 4s… capped at 30s |
| `run()` on `CancelledError` → logs and re-raises | Cancel the task; assert clean exit |

### 7.2 Integration tests

**`tests/integration/resolution_coordinator/test_notification_subscriber_worker.py`** — new file:

Uses `testcontainers` Redis (same pattern as existing Redis integration tests).

| Test | Scenario |
|------|----------|
| Publish to channel → `waiter.notify()` called with correct `triad_key` | Round-trip through real Redis |
| Worker reconnects after Redis restart and resumes delivery | Container restart during test |

### 7.3 BDD

**`tests/feature/resolution_coordinator/notification_subscriber.feature`** — new file:

```gherkin
Feature: Cross-instance ERE outcome notification

  Scenario: ERE outcome processed by one instance unblocks waiter on another
    Given two AsyncResolutionWaiter instances sharing a Redis Pub/Sub channel
    And instance A is waiting on triad_key "abc123"
    When instance B publishes "abc123" to the notifications channel
    Then instance A's event is set within 1 second
    And instance B's waiter has no live event for "abc123" (no-op)

  Scenario: Notification lost during subscriber reconnect degrades to timeout
    Given a NotificationSubscriberWorker is connected to Redis
    And a waiter is waiting on triad_key "xyz789" with a 2-second timeout
    When the Redis connection drops before the notification is published
    Then the waiter times out without receiving a signal
    And the worker reconnects and resumes processing subsequent messages
```

---

## 8. Implementation Order

1. **Config** — add `ERS_NOTIFICATIONS_CHANNEL` to `RedisConfig`; add unit test for default value
2. **`publish_notification()`** — add method to `RedisEREClient`; add unit tests
3. **`NotificationSubscriberWorker`** — implement `start`/`stop`/`run` with reconnect; add unit tests
4. **Lifespan wiring** — update `app.py` (change injection + add subscriber worker)
5. **Integration test** — round-trip through real Redis (testcontainers)
6. **BDD feature** — implement step definitions and run scenarios
7. **Smoke test** — verify `make test` passes green

---

## 9. Decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Which client for `publish_notification`? | Reuse `app.state.redis_client` — `aioredis.Redis` uses a connection pool; LPUSH and PUBLISH draw from it independently without interference. No fourth connection. |
| 2 | Subscriber connection ownership? | Inject `RedisConnectionConfig`; the worker creates and owns its `aioredis.Redis` internally. Consistent with how `OutcomeIntegrationWorker` is structured; testable via testcontainers without class-level mocking. |
| 3 | Channel name default? | `ers_notifications` (underscore) — consistent with existing channel names `ere_requests` and `ere_responses`. The env var is `ERS_NOTIFICATIONS_CHANNEL`. |
