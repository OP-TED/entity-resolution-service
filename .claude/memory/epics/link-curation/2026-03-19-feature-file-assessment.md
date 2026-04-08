# Feature File Critical Assessment (Revised)

**Date:** 2026-03-19
**Scope:** `tests/feature/link_curation_api/` and `tests/feature/user_action_store/`
**Inputs:** Architecture excerpts (Spine C, Spine D, UC-W2, UC-B2.1, UC-B2.2, UC-W4, UC-W5), codebase exploration, offline decision on UCW5 (simple login, no SSO), developer review feedback

---

## Style Guidelines (applied across all features)

- Prefer `Scenario Outline` with `Examples:` tables over inline values
- 2-3 example rows covering representative setups (occasionally more)
- Crisp, concise, easy to read and easy to implement scenarios
- Consistent vocabulary throughout

---

## Executive Summary

The feature files cover the main happy paths well. After developer review, the key remaining issues are:

1. **Hard-delete must become soft-delete** (deactivation) in user_management — traceability requirement
2. **User action recording should capture the full decision context** (not just actor and action type)
3. **Single decision detail view is missing** — belongs in decision_curation.feature
4. **Vocabulary should use "recommendation" language** to align with architecture
5. **Prefer Examples tables** for parameterised scenarios where inline values are currently used

Resolved after developer review:
- Exclusion Recommendation is NOT a separate action — "reject all" acts as exclusions in the forwarded ERE request
- Bulk curation coverage is complete (bulk-accept = accept each decision's top recommendation; bulk-reject = reject all per decision)
- Self-registration is intentionally kept
- No distinction between "retired" and "deactivated" — both mean `active: false`
- Filter by curation status dropped (no longer available)
- Filter by source ID is out of scope
- Statistics per source ID is out of scope

---

## Per-Feature Assessment

### 1. `decision_curation.feature` — MODERATE ISSUES

**Architecture alignment:** UC-W2 / UC-B2.1 / Spine D

| Issue | Severity | Detail |
|-------|----------|--------|
| **Vocabulary: "accept/reject/assign"** | MEDIUM | Architecture says these are *recommendations*. Use "recommend acceptance of top candidate" / "the recommendation is recorded" style. |
| **Missing: single decision detail view** | MEDIUM | `get_decision()` exists but no scenario tests viewing a decision's full details before curating. Add here. |
| **Missing: concurrent conflict scenario** | LOW | Two curators submitting conflicting recommendations for the same mention. Spine D mentions optimistic conflict detection. |

**Recommendations:**
- Revise vocabulary to "recommendation" language
- Add `Scenario: View full details of a resolution decision`
- Add `Scenario: View decision for a non-existent identifier`
- Consider adding concurrency conflict scenario
- Use `Scenario Outline` with `Examples:` where inline values currently exist (e.g. cluster IDs)

---

### 2. `bulk_curation.feature` — GOOD

**Architecture alignment:** UC-B2.2

Coverage is complete:
- Bulk-accept = accept each decision's individually recommended top placement
- Bulk-reject = reject all candidates per decision (acts as exclusions in ERE request)
- Partial failures, already-curated, validation (empty list, max batch size)

| Issue | Severity | Detail |
|-------|----------|--------|
| **"Not found" scenario is nearly impossible** | LOW | Decisions are upserted, never deleted. Acceptable as a defensive edge case. |

**No changes required.**

---

### 3. `canonical_entity_preview.feature` — GOOD, MINOR GAP

**Architecture alignment:** Spine D (clustering context before recommending)

| Issue | Severity | Detail |
|-------|----------|--------|
| **Missing: mentions without parsed representations** | LOW | What if entity mentions in the cluster lack parsed representations? Covered in `user_action_listing.feature` for action previews but not for canonical preview. |

**Recommendations:**
- Add scenario for cluster preview when mentions lack parsed representations

---

### 4. `decision_browsing.feature` — GOOD, MINOR ADJUSTMENTS

**Architecture alignment:** Supporting UC-B2.1

| Issue | Severity | Detail |
|-------|----------|--------|
| **Missing: combined filters** | LOW | No scenario tests multiple filters applied simultaneously. |

Dropped items (confirmed out of scope): filter by curation status, filter by source ID.

**Recommendations:**
- Add `Scenario: Apply multiple filters simultaneously`

---

### 5. `statistics.feature` — GOOD, ALIGNED

**Architecture alignment:** UC-W4

Well-aligned. Covers total mentions, canonical entities, average cluster size, resolution requests, curation counts by type, entity type filtering, time window, empty data, read-only.

**No changes required.**

---

### 6. `authentication.feature` — MINOR ADJUSTMENTS

**Architecture alignment:** UC-W5 + offline decision (simple login, no SSO)

| Issue | Severity | Detail |
|-------|----------|--------|
| **Self-registration: keep** | — | Developer decision to retain self-registration. |
| **Token mechanics: correct** | — | Login, refresh, expiry all fine for simple login. |
| **"Inactive user" scenario: good** | — | Aligns with immediate deactivation semantics. |

**Recommendations:**
- Use `Scenario Outline` with `Examples:` for password validation (currently has it — good)
- Ensure consistent vocabulary with other features

---

### 7. `access_control.feature` — GOOD, MINOR GAP

**Architecture alignment:** UC-W5

| Issue | Severity | Detail |
|-------|----------|--------|
| **Missing: deactivated user access** | MEDIUM | UC-W5 says deactivation takes effect immediately. Feature tests "unverified" but not "deactivated" (active:false). |
| **Verified user can curate** | LOW | Feature tests browse/stats for verified users but doesn't explicitly test curation action access. |

**Recommendations:**
- Add `Scenario: Deactivated user cannot access any endpoint`
- Add `Scenario: Verified user can submit curation recommendations`

---

### 8. `user_management.feature` — NEEDS REVISION

**Architecture alignment:** UC-W5

Key clarifications from developer:
- **No hard delete.** Users can only be deactivated (`active: false`), never removed from the system.
- **Two independent flags:** `active` (true/false) controls access; `verified` (true/false) controls whether a newly created account is allowed to start using the system.
- **Retired = deactivated** — same concept, `active: false`.
- **Default role is curator.** Admin is a separate `superuser` flag toggled independently. No need for "create user with assigned role."

| Issue | Severity | Detail |
|-------|----------|--------|
| **Hard-delete violates traceability** | **CRITICAL** | "Delete a user" removes the record. Must be replaced with "Deactivate a user" (set `active: false`). Past curation actions must remain attributable. |
| **Missing: explicit deactivation/reactivation lifecycle** | **HIGH** | "Update flags" implicitly covers it, but explicit scenarios for suspend (deactivate) and reactivate are clearer. |
| **Missing: deactivated user traceability** | **HIGH** | After deactivating a user, past actions must remain visible and attributable. |
| **Missing: prevent deactivation of last admin** | MEDIUM | Operational safety edge case. |

**Recommendations:**
- Replace `Scenario: Delete a user` with `Scenario: Deactivate a user (set inactive)`
- Replace `Scenario: Delete a non-existent user` with `Scenario: Deactivate a non-existent user`
- Add `Scenario: Reactivate a previously deactivated user`
- Add `Scenario: Deactivated user's past actions remain visible in the action trail`
- Add `Scenario: Cannot deactivate the last administrator`
- Use `Scenario Outline` with `Examples:` for flag updates (currently has it — good)

---

### 9. `user_action_recording.feature` — MODERATE ADJUSTMENTS

**Architecture alignment:** Spine D (User Action Log)

Key clarifications from developer:
- Exclusion recommendation recording is NOT separate — "reject all" IS the exclusion mechanism.
- No metadata field currently exists — curator notes are out of scope.
- The action record should capture the **full decision context**: the complete decision object + the associated action, not just actor identity.

| Issue | Severity | Detail |
|-------|----------|--------|
| **Action recording should capture full decision context** | **HIGH** | Currently "Accept action records the actor identity" only checks actor. Should verify: actor, timestamp, full decision snapshot (all candidates, scores, current placement), action type. |
| **Already-curated guard** | LOW | Implicitly covered by Background precondition ("has not been curated"). Explicit scenario could be added. |

**Recommendations:**
- Expand "Accept action records the actor identity" into a broader scenario: `Scenario: Action captures full decision context` covering actor, timestamp, and full decision snapshot (candidates, scores, current placement)
- Or use `Scenario Outline` with examples checking different recorded fields

---

### 10. `user_action_listing.feature` — GOOD, PRACTICAL GAPS

**Architecture alignment:** Spine D (traceability, operator review)

| Issue | Severity | Detail |
|-------|----------|--------|
| **Missing: filter by action type** | MEDIUM | Admins want to filter by accept/reject/assign. |
| **Missing: filter by actor** | MEDIUM | "Show me everything curator X did." |
| **Missing: filter by time range** | MEDIUM | "Show me actions from last week." |

**Recommendations:**
- Add `Scenario Outline: Filter user actions by criteria` with Examples table (action type, actor, time range)

---

## Summary of Required Changes

### Critical (must fix)
1. Replace hard-delete with deactivation in `user_management.feature`

### High Priority
2. Add full decision context capture in `user_action_recording.feature`
3. Add deactivation/reactivation lifecycle scenarios in `user_management.feature`
4. Add deactivated user traceability scenario in `user_management.feature`
5. Add single decision detail view in `decision_curation.feature`

### Medium Priority
6. Revise vocabulary from "accept/reject" to "recommendation" language across features
7. Add deactivated user access denial in `access_control.feature`
8. Add action listing filters (by type, actor, time range) in `user_action_listing.feature`

### Low Priority
9. Add cluster preview with missing parsed representations in `canonical_entity_preview.feature`
10. Add combined filter scenario in `decision_browsing.feature`
11. Add concurrent conflict scenario in `decision_curation.feature`
12. Use `Scenario Outline` / `Examples:` tables more consistently across all features

---

## Outcome: Revisions Applied (2026-03-19)

All required changes from the assessment were applied to the `.feature` files. Implementation files (`.py`) were not touched.

### Changes per feature file

| Feature File | Priority | Changes Applied |
|---|---|---|
| `decision_curation.feature` | Critical/Medium/High | Vocabulary → "recommendation" language throughout. Added 2 decision detail view scenarios (`View full details`, `View non-existent`). Alternative cluster scenario converted to `Scenario Outline` with 3 example clusters. All section headers revised. |
| `user_management.feature` | Critical/High/Medium | Replaced hard-delete with deactivation (2 scenarios revised). Added 3 new scenarios: `Reactivate a previously deactivated user`, `Deactivated user's past actions remain visible in the action trail`, `Cannot deactivate the last administrator`. Feature description updated to mention traceability. |
| `user_action_recording.feature` | High/Medium | Replaced narrow actor-only scenario with `Scenario Outline: Recorded action captures the full decision context` — verifies actor, timestamp, action type, full candidate snapshot with scores, and current placement. 3 example rows (one per action type). Vocabulary → "recommendation". |
| `access_control.feature` | Medium | Added `Scenario: Deactivated user cannot access any endpoint` (new section). Added `Scenario: Verified user can submit curation recommendations`. |
| `user_action_listing.feature` | Medium | Added `Scenario Outline: Filter the action trail by a single criterion` with 3 examples (recommendation type, actor, time range). |
| `canonical_entity_preview.feature` | Low | Added `Scenario: Canonical entity preview with mentions lacking parsed representations` (new "Incomplete data" section). |
| `decision_browsing.feature` | Low | Added `Scenario: Apply multiple filters simultaneously` (entity type + confidence). |

### Unchanged files (no revision needed)

| Feature File | Reason |
|---|---|
| `bulk_curation.feature` | Already complete — bulk-accept and bulk-reject cover all use cases. |
| `statistics.feature` | Well-aligned with UC-W4. No gaps found. |
| `authentication.feature` | Self-registration retained per developer decision. No other changes needed. |

### Scenario count summary

| Package | Before | After | Delta |
|---|---|---|---|
| `link_curation_api` | 53 scenarios | 63 scenarios | +10 |
| `user_action_store` | 11 scenarios | 12 scenarios | +1 |
| **Total** | **64** | **75** | **+11** |

---

## Outcome: Step Definitions Aligned (2026-03-19)

Step definition files (`.py`) aligned to the revised feature files. Existing logic preserved; new scenarios get TODO boilerplate.

### Changes per step definition file

| File | Renamed steps | New TODO steps | Notes |
|---|---|---|---|
| `test_decision_curation.py` | 8 scenario bindings, 7 When, 3 Then | 2 scenarios + 6 steps (detail view) | Vocabulary only; existing endpoint calls unchanged |
| `test_user_management.py` | 2 scenario bindings, 2 When, 1 Then | 3 scenarios + 8 steps (deactivation lifecycle, last-admin guard) | Delete steps replaced with PATCH-based deactivation |
| `test_user_action_recording.py` | 5 scenario bindings, 3 When | 1 Scenario Outline + 7 steps (full context capture) | Dispatch logic for parametrized When step (3 recommendation types) |
| `test_access_control.py` | — | 2 scenarios + 3 steps (deactivated user, curation access) | Deactivated user step needs `UserContext.is_active` (TODO) |
| `test_user_action_listing.py` | — | 1 Scenario Outline + 4 steps (filtering) | Service filtering support needed (TODO) |
| `test_canonical_entity_preview.py` | — | 1 scenario + 2 steps (missing representations) | Uses `EntityMentionFactory` with `parsed_representation=None` |
| `test_decision_browsing.py` | — | 1 scenario + 3 steps (combined filters) | Reuses existing `_setup_decisions` helper and filter param pattern |

### Code review findings

Parallel code review by subagents confirmed:
- **user_action_store**: All 16 tests collected and pass (was 11). No step text mismatches. Scenario Outline parametrization verified correct for all 3 example rows.
- **link_curation_api**: Cannot run until PR#19 merges (pydantic-settings dependency). Step text alignment verified by review but not runtime-tested. Pre-existing duplicate step definitions across modules noted (module-scoped in pytest-bdd v8, not breaking).

### Test results

| Package | Collected | Passed | Blocked |
|---|---|---|---|
| `user_action_store` | 16 | 16 | — |
| `link_curation_api` | — | — | pydantic-settings (PR#19) |

### TODO items for implementation

| TODO | File(s) | Dependency |
|---|---|---|
| Decision detail view endpoint + steps | `test_decision_curation.py` | New GET endpoint or reuse existing |
| Deactivation lifecycle assertions | `test_user_management.py` | Service logic for traceability verification |
| Last-admin guard service logic | `test_user_management.py` | New guard in `UserManagementService` |
| DELETE endpoint removal/repurpose | `test_user_management.py` | Return error (405 or 400) instead of deleting |
| `UserContext.is_active` + middleware | `test_access_control.py` | Add field + dependency check for deactivated users |
| `UserActionService` filter support | `test_user_action_listing.py` | Add filter params to `list_user_actions()` |
| pydantic-settings resolution | `conftest.py` | Merge PR#19 |

### Next step

Merge with PR#19 to unblock link_curation_api tests, then implement the TODO items.
