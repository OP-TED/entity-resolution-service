# Task 6.7 — ERS REST API Wiring

## Goal

Connect the coordinator services built in Tasks 6.3 and 6.5 to the ERS REST API
entrypoint. Replace all `NotImplementedError` stubs in `dependencies.py` with real
providers. Wire `AsyncResolutionWaiter` as a process-scoped singleton in the lifespan.

This task is **pure plumbing** — no new business logic, no new domain models.

---

## What Needs Wiring

From reading `src/ers/ers_rest_api/entrypoints/api/dependencies.py`:
- `get_resolution_coordinator` → raises `NotImplementedError`
- `get_decision_store` → raises `NotImplementedError`
- `get_refresh_bulk_service` → delegates to `get_decision_store` (also broken)

`AsyncResolutionWaiter` is not yet present anywhere in the app lifecycle.

---

## Part 1 — `AsyncResolutionWaiter` Singleton in Lifespan

`AsyncResolutionWaiter` must be created **once** at app startup and shared between:
- `ResolutionCoordinatorService` (waiter side — awaits signals)
- `OutcomeIntegrationService` / EPIC-05 (signaller side — calls `notify`)

Find the FastAPI lifespan function (likely in
`src/ers/ers_rest_api/entrypoints/api/app.py` or a `lifespan.py` near it).
Add `AsyncResolutionWaiter` instantiation:

```python
from ers.resolution_coordinator.services.async_resolution_waiter import AsyncResolutionWaiter

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup (mongo, redis, worker) ...
    app.state.waiter = AsyncResolutionWaiter()
    yield
    # ... existing shutdown ...
```

The `OutcomeIntegrationService` (EPIC-05) already accepts an optional
`on_outcome_stored` async callback. In the lifespan, after both the waiter and the
worker are initialised, wire the callback:

```python
# After worker and waiter are both created:
outcome_worker.set_callback(app.state.waiter.notify)
# OR, if the worker/service accepts the callback at construction time:
OutcomeIntegrationService(..., on_outcome_stored=app.state.waiter.notify)
```

Check the `OutcomeIntegrationWorker` / `OutcomeIntegrationService` constructor
to determine the correct wiring point — do NOT guess; read the existing lifespan
code and the EPIC-05 service interface before writing.

---

## Part 2 — `dependencies.py` Rewire

### 2a. New real service providers

Add the following to `dependencies.py`, using the same `Annotated[..., Depends(...)]`
pattern as all existing providers:

```python
# Real DecisionStoreService (replaces the ABC stub for new coordinator wiring)
async def get_decision_store_service(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> DecisionStoreService:
    return DecisionStoreService(repository=MongoDecisionRepository(db))


# RequestRegistryService (needed by both coordinator services)
async def get_request_registry_service(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> RequestRegistryService:
    return RequestRegistryService(
        resolution_repo=MongoResolutionRequestRepository(db),
        lookup_repo=MongoLookupStateRepository(db),
        hasher=SHA256ContentHasher(),
        rdf_config=get_rdf_config(),   # follow existing pattern for RDF config loading
    )


# AsyncResolutionWaiter from app.state (singleton)
def get_waiter(request: Request) -> AsyncResolutionWaiter:
    return request.app.state.waiter


# ResolutionCoordinatorService
async def get_resolution_coordinator_service(
    registry:  Annotated[RequestRegistryService,  Depends(get_request_registry_service)],
    publisher: Annotated[EREPublishService,        Depends(get_ere_publish_service)],
    decisions: Annotated[DecisionStoreService,     Depends(get_decision_store_service)],
    waiter:    Annotated[AsyncResolutionWaiter,    Depends(get_waiter)],
) -> ResolutionCoordinatorService:
    return ResolutionCoordinatorService(registry, publisher, decisions, waiter)


# BulkRefreshCoordinatorService
async def get_bulk_refresh_coordinator_service(
    registry:  Annotated[RequestRegistryService, Depends(get_request_registry_service)],
    decisions: Annotated[DecisionStoreService,   Depends(get_decision_store_service)],
) -> BulkRefreshCoordinatorService:
    return BulkRefreshCoordinatorService(registry, decisions)
```

`get_ere_publish_service` likely already exists or is easily constructed from the Redis
client in `app.state`. Follow the existing pattern for Redis adapter construction.

### 2b. Update existing orchestrator providers

Replace the stubs:

```python
# BEFORE
async def get_resolution_coordinator(...) -> ResolutionCoordinatorServiceABC:
    raise NotImplementedError(...)

# AFTER — delegate to the real provider
async def get_resolve_service(
    coordinator: Annotated[ResolutionCoordinatorService,
                           Depends(get_resolution_coordinator_service)],
) -> ResolveService:
    return ResolveService(resolution_coordinator=coordinator)


async def get_refresh_bulk_service(
    coordinator: Annotated[BulkRefreshCoordinatorService,
                           Depends(get_bulk_refresh_coordinator_service)],
) -> RefreshBulkService:
    return RefreshBulkService(bulk_coordinator=coordinator)
```

**Keep `get_decision_store` and `get_lookup_service` stubs intact** — `LookupService`
still depends on `ResolutionDecisionStoreServiceABC`, which is a separate retirement
tracked outside this Epic. Do not break it further; just leave it as-is.

---

## Part 3 — `ResolveService` Mapping Update

`ResolveService` currently calls `coordinator.resolve(request.mention)` returning
`EntityMentionResolutionResult`. It needs to:
1. Call `coordinator.resolve_single(mention)` → returns `Decision`
2. Map `Decision` → `EntityMentionResolutionResult`

**Provisional detection:** Check whether `Decision` or `ClusterReference` already
carries a `is_provisional` flag or a `ResolutionOutcome` field. If not, derive it:

```python
from ers.resolution_decision_store.adapters.provisional_id import derive_provisional_cluster_id

def _is_provisional(decision: Decision) -> bool:
    expected = derive_provisional_cluster_id(decision.about_entity_mention)
    return decision.current_placement.cluster_id == expected
```

Map to the API DTO:

```python
EntityMentionResolutionResult(
    identified_by=decision.about_entity_mention,
    canonical_entity_id=decision.current_placement.cluster_id,
    status=ResolutionOutcome.PROVISIONAL if _is_provisional(decision)
           else ResolutionOutcome.CANONICAL,
)
```

For **bulk resolve**, add `handle_resolve_bulk` to `ResolveService`:

```python
async def handle_resolve_bulk(
    self, request: BulkResolveRequest
) -> BulkResolveResponse:
    mentions = [r.mention for r in request.mentions]
    results  = await self._coordinator.resolve_bulk(mentions)
    return BulkResolveResponse(
        results=[
            self._map_to_result(r) if isinstance(r, Decision)
            else self._map_error_to_result(r, mentions[i].identifiedBy)
            for i, r in enumerate(results)
        ]
    )
```

`_map_error_to_result` constructs an `EntityMentionResolutionResult` with the
`error` field populated from the exception type (no `canonical_entity_id`/`status`).

## Part 4 — `RefreshBulkService` Delegation

`RefreshBulkService` currently reaches into `ResolutionDecisionStoreServiceABC`.
Replace its body to delegate to `BulkRefreshCoordinatorService`:

```python
class RefreshBulkService:
    def __init__(self, bulk_coordinator: BulkRefreshCoordinatorService) -> None:
        self._coordinator = bulk_coordinator

    async def handle_refresh_bulk(self, request: RefreshBulkRequest) -> RefreshBulkResponse:
        page = await self._coordinator.refresh_bulk(
            source_id=request.source_id,
            cursor=request.continuation_cursor,
            page_size=request.limit,
        )
        deltas = [
            LookupResponse(
                identified_by=d.about_entity_mention,
                cluster_reference=d.current_placement,
                last_updated=d.updated_at,
            )
            for d in page.items
        ]
        return RefreshBulkResponse(
            deltas=deltas,
            has_more=page.next_cursor is not None,
            continuation_cursor=page.next_cursor,
        )
```

---

## Files to Create / Modify

| Action | File |
|--------|------|
| Modify | `src/ers/ers_rest_api/entrypoints/api/app.py` (or lifespan file) — add `AsyncResolutionWaiter` to `app.state` and wire callback |
| Modify | `src/ers/ers_rest_api/entrypoints/api/dependencies.py` — add real providers, update orchestrator providers |
| Modify | `src/ers/ers_rest_api/services/resolve_service.py` — update to use `ResolutionCoordinatorService`, add mapping |
| Modify | `src/ers/ers_rest_api/services/refresh_bulk_service.py` — delegate to `BulkRefreshCoordinatorService` |
| Modify | `tests/unit/ers_rest_api/services/test_resolve_service.py` — update mocks and assertions |

---

## Unit Tests

Update `tests/unit/ers_rest_api/services/test_resolve_service.py`:
- Mock `ResolutionCoordinatorService` (not the old ABC)
- `resolve_single` returns a `Decision` → assert mapping to `EntityMentionResolutionResult`
- Test canonical mapping (cluster_id ≠ provisional) → `status = CANONICAL`
- Test provisional mapping (cluster_id == `derive_provisional_cluster_id(...)`) → `status = PROVISIONAL`
- Test bulk: mixed Decision + exception results → correct `BulkResolveResponse`

Add `tests/unit/ers_rest_api/services/test_refresh_bulk_service.py` (or update existing):
- Mock `BulkRefreshCoordinatorService`
- `refresh_bulk` returns a `CursorPage[Decision]` → assert mapping to `RefreshBulkResponse`
- `SourceNotFoundException` → assert appropriate error response

---

## Definition of Done

- [ ] `get_resolution_coordinator` and `get_refresh_bulk_service` no longer raise `NotImplementedError`
- [ ] `app.state.waiter` is an `AsyncResolutionWaiter` after startup
- [ ] `waiter.notify` is wired as the `OutcomeIntegrationService` callback
- [ ] `ResolveService` maps `Decision` → `EntityMentionResolutionResult` correctly for both canonical and provisional
- [ ] `RefreshBulkService` delegates to `BulkRefreshCoordinatorService`
- [ ] All existing `ers_rest_api` unit tests pass: `poetry run pytest tests/unit/ers_rest_api/ -v`
- [ ] `poetry run pytest tests/feature/ers_rest_api/ -v` — all feature scenarios pass
- [ ] `LookupService` and `get_decision_store` (ABC-based) are untouched and still compile
- [ ] `poetry run pylint src/ers/ers_rest_api/` — no new errors introduced
