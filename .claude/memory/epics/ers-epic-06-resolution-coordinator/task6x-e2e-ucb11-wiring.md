# Task 6X: Wire E2E Step Definitions for UC-B1.1 (post-implementation)

## Context

After EPIC-06 implementation is complete, the e2e test scaffold for UC-B1.1 must be
wired with real service calls. This task is a reminder to do that - do not attempt it
before `ResolutionCoordinatorService` exists and its tests are green.

The scaffold file already exists and defines all scenario bindings and step skeletons.
It only needs the TODO placeholders replaced with real calls.

---

## Prerequisite

EPIC-06 implementation must be complete (all unit + integration tests passing).

---

## Files to Update

| Path | What changes |
|------|-------------|
| `tests/e2e/ucs/test_ucb11_resolve_entity_mention.py` | Replace all TODO placeholders with real `ResolutionCoordinatorService` calls |

## Files to Review (not modify)

| Path | Why |
|------|-----|
| `tests/e2e/ucs/ucb11_resolve_entity_mention.feature` | Gherkin specification - 10 scenarios |
| `tests/feature/resolution_coordinator/test_single_mention_resolution.py` | Reference implementation to follow |
| `tests/feature/resolution_coordinator/test_bulk_resolution.py` | Reference implementation for bulk scenarios |

---

## Scenarios to Wire (10 total)

From `ucb11_resolve_entity_mention.feature`:

1. Canonical resolution (ERE responds within budget) - happy path
2. Provisional draft identifier (ERE timeout) - time budget enforcement
3. Draft determinism (same triad always gets same provisional ID)
4. Idempotent replay (same triad + same content = return existing decision)
5. Idempotency conflict (same triad + different content = rejection)
6. Validation errors (missing/invalid fields in request)
7. Client timeout (overall budget exhausted)
8. ERE unavailability (publish fails)
9. Registry failure
10. Decision Store failure

---

## Pattern to Follow

Use the same `ctx` fixture + `_loop` + `run_until_complete` pattern established in:
- `tests/feature/ere_result_integrator/test_outcome_acceptance.py`
- `tests/e2e/ucs/test_ucb12_integrate_ere_outcomes.py` (task 58 - EPIC-05)

The coordinator requires mocking:
- `RequestRegistryService` (EPIC-01)
- `RDFMentionParserService` (EPIC-02)
- `EREPublishService` (EPIC-03)
- `DecisionStoreService` (EPIC-04)
- `AsyncResolutionWaiter` (EPIC-06 internal)

---

## Key References

| What | Where |
|------|-------|
| `ResolutionCoordinatorService` | `src/ers/resolution_coordinator/services/` (to be created in EPIC-06) |
| Gherkin spec | `tests/e2e/ucs/ucb11_resolve_entity_mention.feature` |
| EPIC-06 spec | `.claude/memory/epics/ers-epic-06-resolution-coordinator/EPIC.md` |
| E2E resolution cycle | `tests/e2e/ucs/test_e2e_resolution_cycle.py` (also needs wiring after EPIC-07) |