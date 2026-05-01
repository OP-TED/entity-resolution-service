# Epic: ERS1-208 — Make ERS Stateless (Cross-Instance BRPOP Fix)

## Status
- **Epic ID:** ERS1-208
- **Branch:** `feature/ERS1-208/make-ers-stateless`
- **Phase:** Complete
- **Last updated:** 2026-05-01
- **Dependencies:** EPIC-06 (AsyncResolutionWaiter), EPIC-05 (ERE Result Integrator — OutcomeIntegrationService), EPIC-07 (app.py lifespan)

---

## 1. Description

ERS ran correctly with a single instance but silently broke under horizontal scale. The root cause: `AsyncResolutionWaiter` holds `asyncio.Event` objects in process RAM. When a different ERS instance wins the BRPOP race for an ERE response, it calls `waiter.notify()` on its own local waiter — which has no live event for that triad. The requesting instance's `event.wait()` expires, falls through to `_issue_provisional()`, and the canonical ERE result may be silently discarded.

**Failure rate:** P(wrong instance wins BRPOP) = (N-1)/N. At N=2 that is 50%; the problem worsens linearly with scale.

**Fix (Option A — Redis Pub/Sub broadcast):** After the BRPOP winner writes the canonical decision to MongoDB, it `PUBLISH`es the `triad_key` to a shared Redis channel (`ers_notifications`). Each ERS instance runs a lightweight subscriber background task that receives all broadcasts and calls `waiter.notify(triad_key)` locally. The instance with a live event unblocks its waiting coroutine; all others discard the no-op silently. `AsyncResolutionWaiter` itself is unchanged.

---

## 2. What Changed

| Component | Change |
|-----------|--------|
| `RedisConfig` (`ers/__init__.py`) | Added `ERS_NOTIFICATIONS_CHANNEL` property (default `ers_notifications`) |
| `RedisEREClient` | Added `publish_notification(channel, triad_key)` method |
| `NotificationSubscriberWorker` | **New file** — asyncio background task; subscribes to channel; exponential backoff reconnect; forwards to local waiter |
| `app.py` lifespan | Changed `on_outcome_stored=waiter.notify` to `lambda key: ere_client.publish_notification(...)`, added subscriber worker start/stop |
| `OutcomeIntegrationService` | None — injected callback changed at wiring point only |
| `AsyncResolutionWaiter` | None |
| `ResolutionCoordinatorService` | None |

New files created:
- `src/ers/resolution_coordinator/entrypoints/__init__.py`
- `src/ers/resolution_coordinator/entrypoints/notification_subscriber_worker.py`

---

## 3. Key Design Decisions

| # | Decision |
|---|----------|
| 1 | `PUBLISH` reuses `app.state.redis_client` connection pool (no extra connection on publish side) |
| 2 | Subscriber creates its own `aioredis.Redis` internally — `SUBSCRIBE` puts a connection in pub/sub mode, incompatible with regular commands |
| 3 | Channel name default: `ers_notifications` (underscores, consistent with `ere_requests`/`ere_responses`) |
| 4 | Backoff: 1s → 2s → 4s, capped at 30s; reset only when frames actually flow (inside `async for` body) |
| 5 | `_subscribed: asyncio.Event` on worker — replaces fragile `asyncio.sleep()` waits in tests |
| 6 | `CancelledError` propagated cleanly; `finally` block ensures `pubsub.unsubscribe()` + `redis_client.aclose()` on all exit paths |

---

## 4. Task Breakdown

| Task | File | Status |
|------|------|--------|
| T1 — Statefulness audit | `2026-05-01-statefulness-audit.md` | ✅ Complete |
| T2 — Option A implementation (config + publish + subscriber + tests + BDD + wiring) | `2026-05-01-option-a-implementation.md` | ✅ Complete |

## Roadmap
- [x] T1: Statefulness audit — identify failure mode, rank options, recommend Option A
- [x] T2: Option A implementation — TDD through all layers; code review; all tests green

---

## 5. Test Coverage

| Layer | Location |
|-------|----------|
| Unit — `publish_notification` | `test/unit/commons/test_redis_client.py` — `TestPublishNotification` |
| Unit — `NotificationSubscriberWorker` | `test/unit/resolution_coordinator/entrypoints/test_notification_subscriber_worker.py` |
| Unit — `ERS_NOTIFICATIONS_CHANNEL` config | `test/unit/commons/adapters/test_app_config.py` — `TestRedisConfig` |
| Integration — round-trip through real Redis | `test/integration/resolution_coordinator/test_notification_subscriber_worker.py` |
| BDD — cross-instance fan-out + reconnect degradation | `test/feature/resolution_coordinator/notification_subscriber.feature` |

---

## 6. Reliability Caveat

Redis Pub/Sub is fire-and-forget — no persistence, no replay. A notification published during a subscriber reconnect gap is permanently lost; the affected waiter times out and issues a provisional result. This is the same fallback as the current single-instance timeout path. The subscriber's auto-reconnect with exponential backoff minimises the gap window, but a small fraction of notifications will be missed under sustained Redis instability.

---

## 7. References

| Topic | Location |
|-------|----------|
| Statefulness audit (full analysis) | `2026-05-01-statefulness-audit.md` |
| Option A implementation spec | `2026-05-01-option-a-implementation.md` |
| AsyncResolutionWaiter | `.claude/memory/epics/ers-epic-06-resolution-coordinator/EPIC.md §5.3` |
| OutcomeIntegrationService | `.claude/memory/epics/ers-epic-05-ere-result-integrator/EPIC.md` |
| Redis adapter | `src/ers/commons/adapters/redis_client.py` |
| Subscriber worker | `src/ers/resolution_coordinator/entrypoints/notification_subscriber_worker.py` |
| App lifespan | `src/ers/ers_rest_api/entrypoints/api/app.py` |