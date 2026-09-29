# EPIC-07 Open Concerns
**Date raised:** 2026-03-25
**Status:** All resolved (2026-04-01, T6.7 implementation)

---

## CONCERN-01 — Potential Tier 2 → Tier 3 import violation [RESOLVED]

**Resolution:** The Coordinator returns `Decision` (er-spec, shared Tier 0).
`ResolveService` in the REST API (Tier 3) maps `Decision` → `EntityMentionResolutionResult`.
No upward dependency exists.

---

## CONCERN-02 — `get_lookup_state` / `advance_snapshot` mixed into ABC [RESOLVED]

**Resolution:** `RefreshBulkService` now delegates to `BulkRefreshCoordinatorService`
(EPIC-06), which internally handles lookup state and snapshot advancement through
`RequestRegistryService`. The `ResolutionDecisionStoreServiceABC` has been deleted —
it had zero upstream dependents.

---

## CONCERN-03 — `/resolve` returns 202 for PROVISIONAL — contradicts Constraint #2 [RESOLVED]

**Decision:** Option A — keep 202 for PROVISIONAL. HTTP 202 Accepted clearly signals
"accepted but not yet final". Constraint #2 in EPIC-07 spec updated accordingly.

---

## CONCERN-04 — EPIC-06 exceptions not handled in EPIC-07 exception handlers [RESOLVED]

**Resolution:** Added specific exception handlers in `exception_handlers.py`:

| Exception | HTTP Status | Error Code |
|-----------|-------------|------------|
| `ParsingFailedException` | 400 | `PARSING_FAILED` |
| `IdempotencyConflictError` | 422 | `IDEMPOTENCY_CONFLICT` |
| `SourceNotFoundException` | 404 | `SOURCE_NOT_FOUND` |
| `ResolutionTimeoutException` | 504 | `SERVICE_TIMEOUT` |

`CoordinatorException` inherits from `ApplicationError`, so unhandled coordinator
errors still fall through to the generic `ApplicationError` → 400 handler.
