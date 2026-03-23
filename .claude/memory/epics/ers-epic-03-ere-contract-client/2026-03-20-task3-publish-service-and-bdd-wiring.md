# Task 3 + BDD Wiring — EREPublishService and Step Definitions

## Part 1 — Task Specification

**Task:** Implement Publish Service and wire BDD step definitions (Task 3 + Task 6 from EPIC roadmap)

**Layer affected:** `services/` (new), `tests/feature/ere_contract_client/` (existing scaffolding replaced)

**Acceptance criteria:**
- `EREPublishService.publish_request()` validates the correlation triad, auto-generates missing `ere_request_id` and `timestamp`, pushes via the injected `AbstractClient`, and returns `ere_request_id`.
- Raises `InvalidRequestError` for incomplete triads (including `entity_mention=None`).
- Maps `TimeoutError` and `redis.exceptions.ConnectionError` to `RedisConnectionError`.
- Re-raises `ChannelUnavailableError` from the adapter unchanged.
- OTel span `ere_contract_client.publish` emitted when OTel is available; no-op otherwise.
- All 17 BDD scenarios pass (1 serialization scenario correctly skipped).
- Full existing test suite (336 tests) stays green.

**Gherkin scenarios covered:**
- `request_publishing.feature`: 8 scenarios (4 optional-field combinations, singleton proposal, 2 auto-metadata, duplicate publish)
- `request_validation_and_transport.feature`: 10 scenarios (4 triad validation, 4 transport failures — 1 skipped, 2 health check)

---
<!-- implementation-log -->
---

## Part 2 — Implementation Log

### What was accomplished

1. **Created** `/src/ers/ere_contract_client/services/__init__.py` (empty package marker).
2. **Created** `/src/ers/ere_contract_client/services/ere_publish_service.py` with `EREPublishService`:
   - `publish_request()` — validates, enriches, spans, pushes.
   - `_validate_triad()` — checks `entity_mention` not None, then all three triad fields are non-empty strings.
   - `_enrich_metadata()` — fills falsy `ere_request_id` with UUID4, fills `None` timestamp with UTC now.
   - OTel via try/except import with `_NoOpSpan` fallback (OTel not yet in `pyproject.toml`).
3. **Replaced stub step definitions** in `test_request_publishing.py` and `test_request_validation_and_transport.py` with real implementations calling `EREPublishService` through `asyncio.new_event_loop()`.

### Key decisions

**`TimeoutError` → `RedisConnectionError` (not `ChannelUnavailableError`):**
The task description mapped `TimeoutError` to `ChannelUnavailableError`, but the EPIC spec (Section 6 error catalogue) clearly states "Redis client raises `redis.ConnectionError` or `redis.TimeoutError`" → `RedisConnectionError`. The feature scenario also expects `connection` error for `response timeout`. The code was aligned to the spec; the task description contained a mapping error.

**OTel graceful fallback:**
`opentelemetry-api` is not in `pyproject.toml` despite being listed as "Available" in EPIC.md §11. Added a try/except import with a `_NoOpSpan` so the service works today and picks up real spans once OTel is added as a dependency. This is a spec divergence that should be resolved by adding `opentelemetry-api` to `pyproject.toml`.

**erspec `ere_request_id` is required at construction:**
`EntityMentionResolutionRequest.ere_request_id` has no default in the erspec Pydantic model. The "auto-generate if absent" flow uses an empty string `""` as the absent sentinel in tests (and the service treats any falsy value as absent). For `entity_mention=None`, `model_construct()` bypasses Pydantic validation in test setup.

**Serialization failure scenario skipped (not falsely passed):**
The service has no explicit `try/except` around serialization because Pydantic models always serialize correctly if constructed validly — serialization errors would only arise from bugs in erspec models. The scenario is skipped with an explanatory message pointing to EPIC.md §6. This is honest: the capability is not yet implemented.

### Deviations from task description

- Removed the `ChannelUnavailableError` mapping for `TimeoutError`; used `RedisConnectionError` per EPIC spec.
- Did not use `asyncio.get_event_loop()` (deprecated in Python 3.12) — used `asyncio.new_event_loop()` in each `when` step.
- FEATURE_FILE path in step files points to the sibling `.feature` file directly (not `../../../feature/...`) since feature files are co-located with step definitions.

### Resulting files

- `/src/ers/ere_contract_client/services/__init__.py`
- `/src/ers/ere_contract_client/services/ere_publish_service.py`
- `/tests/feature/ere_contract_client/test_request_publishing.py`
- `/tests/feature/ere_contract_client/test_request_validation_and_transport.py`

### Test results

- 336 passed, 1 skipped — full unit + feature suite.
- The 1 skip is `serialization failure-serialization` (intentional, documented).
