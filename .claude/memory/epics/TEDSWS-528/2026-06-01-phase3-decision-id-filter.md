# Phase 3 — `decision_id` filter on `/curation/user-actions`

## Task Specification

**Description**: Allow the curation UI to fetch the timeline of curator actions for a
single decision via `/api/v1/curation/user-actions?decision_id={id}`. No new route,
no new DTO beyond extending `UserActionFilters`.

**Layers affected**: domain, adapters, services, entrypoints, commons (index)

**Acceptance criteria**:
- `UserActionFilters` accepts `decision_id` (public API field)
- The service resolves `decision_id` → `Decision.about_entity_mention` via `decision_repository.find_by_id`
- The repository filters by `about_entity_mention` sub-document (stored field on `user_actions` docs)
- `user_actions.about_entity_mention` index declared in `ensure_indexes`
- `decision_id` composes correctly with `action_type` and other filters

**Key design decision**: `UserAction` documents in MongoDB do NOT have a `decision_id`
field. The link is through `about_entity_mention` (EntityMentionIdentifier triad).
The `decision_id` → `about_entity_mention` resolution happens in the service layer.
Two new fields added to `UserActionFilters`:
- `decision_id: str | None` — public, set by the entrypoint
- `about_entity_mention: EntityMentionIdentifier | None` — internal, set by the service

---
<!-- implementation-log -->
---

## Implementation Log

**Date**: 2026-06-01

### What was accomplished

- Added `decision_id` and `about_entity_mention` fields to `UserActionFilters` (domain DTO).
- Added `_resolve_decision_filter` private method to `UserActionService.list_user_actions`
  that performs the `decision_id` → `about_entity_mention` lookup and returns a new
  immutable filter with the resolved field set.
- Extended `MongoUserActionCurationRepository._build_filter_query` to emit
  `{"about_entity_mention": identifier.model_dump(mode="python")}` when the field is set.
- Added `decision_id` query parameter to the `list_user_actions` FastAPI endpoint.
- Declared `user_actions.about_entity_mention` index in `MongoClientManager.ensure_indexes`.
- Wrote 3 BDD scenarios + step definitions in `test_user_actions_filter_by_decision.py`.
- Wrote 3 new repository unit tests (`TestBuildFilterQuery` class).
- Wrote 4 new service unit tests (`TestListUserActionsByDecisionId` class).

### Test counts

- 10 new repo filter tests passing (including 3 new `about_entity_mention` tests)
- 4 new service decision_id resolution tests passing
- 3 new BDD scenario tests passing
- Full `link_curation_api` feature suite: 100 passed, zero regressions
- Pre-existing asyncio_mode strict failures in `TestFindWithCursor` (8 tests) remain unchanged — unrelated to this phase

### Key decisions

1. **No `decision_id` stored on `UserAction`**: The erspec model does not have this
   field and we do not mutate the stored schema. The link is always through the
   `about_entity_mention` triad.

2. **Service-layer resolution**: The `decision_id` → `about_entity_mention` mapping is
   owned by the service (correct layer for use-case orchestration involving two
   domain aggregates). The repository stays decoupled from Decision semantics.

3. **FrozenDTO evolution**: Since `UserActionFilters` is Pydantic frozen, the service
   uses `model_copy(update={...})` to create the resolved filter — no mutation.

4. **Decision not found**: When `find_by_id` returns `None`, the filter is returned
   unchanged (no `about_entity_mention` set). This means no filtering by entity
   mention occurs and all user_actions are returned. This is a graceful degradation —
   the caller passed an unknown decision_id which is effectively a no-op filter.
   Could be made stricter (raise NotFoundError) if the product requires it — deferred.

### Stored field name confirmed

The stored field linking user_actions to decisions is **`about_entity_mention`**
(an embedded `EntityMentionIdentifier` sub-document with fields `source_id`,
`request_id`, `entity_type`). This is the field Phase 5's `$lookup` should use.
