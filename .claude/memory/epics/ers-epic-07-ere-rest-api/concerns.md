# EPIC-07 Open Concerns
**Date raised:** 2026-03-25
**Status:** Pending decisions / investigation

These are issues discovered during the cross-epic clarity gate review that require
a developer decision or code investigation before they can be resolved.

---

## CONCERN-01 — Potential Tier 2 → Tier 3 import violation [CRITICAL — needs investigation]

**Issue:** `ResolutionCoordinatorServiceABC` lives in `ers.resolution_coordinator`
(Tier 2). Its `resolve()` method signature returns `EntityMentionResolutionResult`,
which is defined in `ers.ers_rest_api.domain.resolution` (Tier 3).

If the ABC file imports from `ers.ers_rest_api`, this is a forbidden upward dependency:
Tier 2 importing from Tier 3 violates `.importlinter` rules.

**Investigation needed:** Read
`src/ers/resolution_coordinator/services/resolution_coordinator_service.py` and check
the import block. If `EntityMentionResolutionResult` is imported from `ers.ers_rest_api`,
the fix is to define the return type in `ers.commons` (or in er-spec) and have EPIC-07
services map from the domain type to the API DTO.

**Impact if confirmed:** The ABC return type must change; EPIC-07 service layer needs
a mapping step; EPIC-06 implementation plan needs updating.

---

## CONCERN-02 — `get_lookup_state` / `advance_snapshot` mixed into `ResolutionDecisionStoreServiceABC` [MEDIUM]

**Issue:** `ResolutionDecisionStoreServiceABC` (EPIC-04 interface used by EPIC-07) includes
two methods that actually belong to EPIC-01's `RequestRegistryService`:
- `get_lookup_state(source_id)` — reads `LookupRequestRecord`
- `advance_snapshot(source_id, snapshot)` — advances the delta watermark

The FIXME comments in the code confirm this mismatch. Architecturally,
`RefreshBulkService` needs both the Decision Store and the Request Registry,
but currently accesses both through a single ABC.

**Decision needed:** Should `RefreshBulkService` accept two injected dependencies
(`ResolutionDecisionStoreServiceABC` + `RequestRegistryServiceABC`), or should the
combined ABC be intentionally kept as a convenience façade?

**Impact:** Affects `dependencies.py` wiring and `RefreshBulkService` constructor.

---

## CONCERN-03 — `/resolve` returns 202 for PROVISIONAL — contradicts Architectural Constraint #2 [MEDIUM]

**Issue:** Architectural Constraint #2 states:
> *"Resolve endpoint always returns 200 OK, even for provisional IDs. Status field carries the semantic."*

The actual implementation sets `response.status_code = 202` when
`result.status == ResolutionOutcome.PROVISIONAL`.

These two are contradictory. One of them must change.

**Decision needed:**
- Option A: Keep 202 for PROVISIONAL (remove/update Constraint #2). Rationale: 202 Accepted
  clearly signals "accepted but not yet final" to HTTP clients; aligns with HTTP semantics.
- Option B: Always return 200 (revert the 202 logic). Rationale: simpler, no client-side
  status code branching; semantic communicated by `status` field only.

**Impact:** If Option A: update Constraint #2 and Gherkin scenarios.
If Option B: remove the `response.status_code = 202` branch in `routes.py`.

---

## CONCERN-04 — EPIC-06 exceptions not handled in EPIC-07 exception handlers [MEDIUM]

**Issue:** The Coordinator (EPIC-06) raises errors that are not explicitly handled
in `exception_handlers.py`:

| Exception | Origin | Currently handled? | Expected HTTP |
|-----------|--------|--------------------|---------------|
| `IdempotencyConflictError` | EPIC-01 (subclass `ApplicationError`) | ✅ via `ApplicationError` → 400 | 422 would be more accurate |
| `ParsingFailedError` | EPIC-06 (subclass `CoordinatorError`) | ❓ depends on hierarchy | 400 |
| `ResolutionTimeoutError` | EPIC-06 (subclass `CoordinatorError`) | ❓ depends on hierarchy | 504 |
| `EnginePublishFailedError` | EPIC-06 (subclass `CoordinatorError`) | ❓ depends on hierarchy | Graceful (no HTTP error — provisional returned) |

**Investigation needed:** Check if `CoordinatorError` subclasses `ApplicationError` or
`DomainError`. If neither, these exceptions will produce unhandled 500s with no structured
`ErrorResponse` body.

**Impact:** May require adding specific exception handlers for EPIC-06 error types.
