---
name: EPIC-06 Implementation Progress
description: Resolution Coordinator implementation status — T6.1–T6.3 complete with review fixes, design decisions documented
type: project
---

## Status

Branch: `feature/ERS1-145` — Tasks T6.1, T6.2, T6.3 implemented + code review fixes applied.
Remaining: T6.4 (Decision Store delta extension), T6.5 (BulkRefreshCoordinator), T6.6 (integration tests), T6.7 (REST API wiring).

## Key Implementation Decisions

### T6.2 — AsyncResolutionWaiter: simplified design
- **No `asyncio.Lock`**: all method bodies are synchronous Python (no `await` inside), so no coroutine interleaving is possible in single-threaded asyncio. The lock was cargo-culted from thread-safe patterns.
- **`WeakValueDictionary` replaces manual ref-counting**: callers hold strong refs to events; CPython GC evicts entries when all refs are dropped. `release()` is a no-op (exists for the integration contract).

### T6.3 — ResolutionCoordinatorService: simplified flow
- **No `EnginePublishFailedException` as internal control flow**: `RedisConnectionError`, `ChannelUnavailableError`, and `asyncio.TimeoutError` all caught in one clause, falling through to provisional.
- **`ChannelUnavailableError` caught alongside `RedisConnectionError`**: ERE not subscribed is functionally equivalent to Redis down.
- **`get_or_create` moved before publish**: simplifies flow into a single try/finally for waiter lifecycle. Zero-cost with WeakValueDictionary.
- **`_issue_provisional` extracted**: private method for readability and SRP.
- **`ValueError` added to parsing catch list**: `RequestRegistryService` raises it for empty content.
- **`EntityMentionResolutionRequest` requires `ere_request_id=""`**: empty string sentinel; auto-populated by `EREPublishService._enrich_metadata`.

### Code Review Fixes
- **`derive_provisional_cluster_id` moved to `ers.commons.adapters.provisional_id`**: eliminates cross-module adapter boundary violation. Old location at `ers.resolution_decision_store.adapters.provisional_id` re-exports for backward compat.
- **`resolve_bulk` return type widened to `list[Decision | Exception]`**: `asyncio.gather(return_exceptions=True)` can capture any exception including `IdempotencyConflictError`.
- **StaleOutcomeError exception chain preserved**: `raise ... from exc` instead of bare raise.
- **`ResolutionCoordinatorServiceABC` removed**: `ResolveService`, `dependencies.py`, and their tests updated to reference `ResolutionCoordinatorService` directly. `.resolve()` → `.resolve_single()`.

## How to apply
- T6.4 and T6.5 are independent and can be parallelized.
- T6.7 will do the proper `ResolveService` rewrite (current wiring is a temporary bridge — mock return types still `EntityMentionResolutionResult`, real `resolve_single` returns `Decision`).
- `env_property` triggers pylint `W0143 comparison-with-callable` false positive — suppress with `# pylint: disable=comparison-with-callable` when comparing config values.
