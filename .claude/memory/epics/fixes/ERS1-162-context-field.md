# Add `context` Field to Refresh-Bulk Response — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the `context` field (already part of `erspec.EntityMention`) through the `/resolve` intake path into MongoDB, then return it in each `/refresh-bulk` delta item.

**Architecture:** `erspec.EntityMention` already carries `context: Optional[str]`. `ResolutionRequestRecord` inherits `EntityMention`, so context flows into MongoDB automatically via the existing `model_dump()` path in `register_resolution_request`. The only production changes needed are: (1) add `context` to `LookupResponse`, (2) add a batch context-fetch method to the request registry, (3) enrich `RefreshBulkService` deltas with the fetched context, (4) wire the new registry dependency into the DI.

**Tech Stack:** Python, FastAPI, Pydantic v2, Motor (async MongoDB), pytest, pytest-asyncio (auto mode), make

---

## Context

ERS-1162: The `/refresh-bulk` delta response must include `context` — the optional free-text metadata users attach to each entity mention when calling `/resolve`. The new erspec release (0.1.0) adds `context: Optional[str]` to `EntityMention`, so the field is already in the intake model and will be stored in `resolution_requests` via `ResolutionRequestRecord`'s inherited `model_dump()`. What remains is to read it back and expose it in the refresh-bulk response.

The `context` field is **optional** (`str | None = None`) — same as erspec defines it.

---

## Key Insight: What Does NOT Need to Change

| Component | Why no change needed |
|-----------|----------------------|
| `EntityMentionResolutionRequest` | `mention: EntityMention` already has `context` via erspec |
| `ResolutionRequestRecord` | Inherits `EntityMention`; `model_dump()` includes `context` automatically |
| `register_resolution_request` | Already does `**entity_mention.model_dump(exclude={"parsed_representation"})` — `context` flows in |
| `ResolutionCoordinatorService` | Passes `entity_mention` as-is; `context` is inside |
| `ResolveService` | No change; coordinator receives full `EntityMention` with `context` |

---

## File Map

| File | Change |
|------|--------|
| `src/ers/ers_rest_api/domain/lookup.py` | Add `context` to `LookupResponse` and `BulkLookupResult` |
| `src/ers/request_registry/adapters/records_repository.py` | Add `find_contexts_by_triads` abstract + impl |
| `src/ers/request_registry/services/request_registry_service.py` | Add `get_contexts_for_triads` |
| `src/ers/ers_rest_api/services/lookup_service.py` | Add `registry_service`; fetch context in `handle_lookup` |
| `src/ers/ers_rest_api/services/refresh_bulk_service.py` | Add `registry_service`; batch-fetch + populate context |
| `src/ers/ers_rest_api/entrypoints/api/dependencies.py` | Wire `registry_service` into `get_lookup_service` and `get_refresh_bulk_service` |

---

## Task 1 — Verify `context` already stored: add tests for `ResolutionRequestRecord`

**Files:**
- Test only: `tests/unit/request_registry/domain/test_records.py`

No production code change — `ResolutionRequestRecord` inherits `context` from `erspec.EntityMention`. These tests confirm the new erspec field is visible and usable.

- [ ] **Step 1: Write the tests** (add to existing `TestResolutionRequestRecord` class)

```python
def test_context_defaults_to_none(self, identifier, now):
    record = ResolutionRequestRecord(
        identifiedBy=identifier,
        content='{"name": "Acme Corp"}',
        content_type="application/ld+json",
        content_hash=VALID_HASH,
        received_at=now,
    )
    assert record.context is None

def test_context_accepts_string(self, identifier, now):
    record = ResolutionRequestRecord(
        identifiedBy=identifier,
        content='{"name": "Acme Corp"}',
        content_type="application/ld+json",
        content_hash=VALID_HASH,
        received_at=now,
        context="procurement round 3",
    )
    assert record.context == "procurement round 3"
```

- [ ] **Step 2: Run to verify they already pass** (no prod change expected)

```bash
poetry run pytest tests/unit/request_registry/domain/test_records.py -v
```
Expected: ALL PASS (context is inherited from EntityMention)

- [ ] **Step 3: Commit**

```bash
git add tests/unit/request_registry/domain/test_records.py
git commit -m "test(request-registry): verify context field inherited from EntityMention in ResolutionRequestRecord"
```

---

## Task 2 — Verify `context` accepted via `/resolve` HTTP layer

**Files:**
- Test only: `tests/unit/ers_rest_api/api/test_resolve.py`

No production code change — `EntityMentionResolutionRequest.mention` is `EntityMention`, which already has `context`.

- [ ] **Step 1: Write the tests** (add to `TestResolveEndpoint`)

```python
async def test_context_in_mention_accepted_in_request(
    self, client, resolve_service
) -> None:
    resolve_service.handle_resolve.return_value = EntityMentionResolutionResult(
        identified_by=EntityMentionIdentifier(
            source_id="SYSTEM_A", request_id="req-001", entity_type="ORGANISATION"
        ),
        canonical_entity_id="cluster-010",
        status=ResolutionOutcome.CANONICAL,
    )
    payload = {
        "mention": {
            "identifiedBy": {
                "source_id": "SYSTEM_A",
                "request_id": "req-001",
                "entity_type": "ORGANISATION",
            },
            "content": '{"name": "Acme Corp"}',
            "content_type": "application/ld+json",
            "context": "procurement round 3",
        },
    }
    response = await client.post("/api/v1/resolve", json=payload)
    assert response.status_code == 200
    call_arg = resolve_service.handle_resolve.call_args[0][0]
    assert call_arg.mention.context == "procurement round 3"

async def test_context_absent_in_mention_defaults_to_none(
    self, client, resolve_service
) -> None:
    resolve_service.handle_resolve.return_value = EntityMentionResolutionResult(
        identified_by=EntityMentionIdentifier(
            source_id="SYSTEM_A", request_id="req-001", entity_type="ORGANISATION"
        ),
        canonical_entity_id="cluster-010",
        status=ResolutionOutcome.CANONICAL,
    )
    response = await client.post("/api/v1/resolve", json=VALID_RESOLVE_PAYLOAD)
    assert response.status_code == 200
    call_arg = resolve_service.handle_resolve.call_args[0][0]
    assert call_arg.mention.context is None
```

- [ ] **Step 2: Run to verify they already pass**

```bash
poetry run pytest tests/unit/ers_rest_api/api/test_resolve.py -v
```
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/ers_rest_api/api/test_resolve.py
git commit -m "test(ers-rest-api): verify context field accepted inside mention on /resolve"
```

---

## Task 3 — `LookupResponse` and `BulkLookupResult` gain `context` field

**Files:**
- Modify: `src/ers/ers_rest_api/domain/lookup.py`
- Test: `tests/unit/ers_rest_api/domain/test_dto_validators.py`

- [ ] **Step 1: Write the failing tests** (add two new classes; import `LookupResponse`, `BulkLookupResult`, `ClusterReference`, `datetime`, `UTC` as needed)

```python
class TestLookupResponseContext:
    def test_context_defaults_to_none(self) -> None:
        resp = LookupResponse(
            identified_by=EntityMentionIdentifier(
                source_id="S", request_id="R", entity_type="ORGANISATION"
            ),
            cluster_reference=ClusterReference(
                cluster_id="cl-1", confidence_score=0.9, similarity_score=0.85
            ),
            last_updated=datetime(2026, 3, 15, tzinfo=UTC),
        )
        assert resp.context is None

    def test_context_accepts_string(self) -> None:
        resp = LookupResponse(
            identified_by=EntityMentionIdentifier(
                source_id="S", request_id="R", entity_type="ORGANISATION"
            ),
            cluster_reference=ClusterReference(
                cluster_id="cl-1", confidence_score=0.9, similarity_score=0.85
            ),
            last_updated=datetime(2026, 3, 15, tzinfo=UTC),
            context="procurement context",
        )
        assert resp.context == "procurement context"


class TestBulkLookupResultContext:
    def test_context_defaults_to_none_on_success(self) -> None:
        result = BulkLookupResult(
            identified_by=EntityMentionIdentifier(
                source_id="S", request_id="R", entity_type="ORGANISATION"
            ),
            cluster_reference=ClusterReference(
                cluster_id="cl-1", confidence_score=0.9, similarity_score=0.85
            ),
            last_updated=datetime(2026, 3, 15, tzinfo=UTC),
        )
        assert result.context is None

    def test_context_accepts_string_on_success(self) -> None:
        result = BulkLookupResult(
            identified_by=EntityMentionIdentifier(
                source_id="S", request_id="R", entity_type="ORGANISATION"
            ),
            cluster_reference=ClusterReference(
                cluster_id="cl-1", confidence_score=0.9, similarity_score=0.85
            ),
            last_updated=datetime(2026, 3, 15, tzinfo=UTC),
            context="procurement context",
        )
        assert result.context == "procurement context"
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/unit/ers_rest_api/domain/test_dto_validators.py -v
```
Expected: FAIL — `context` not a field on `LookupResponse` or `BulkLookupResult`

- [ ] **Step 3: Implement — add `context` to both models in `lookup.py`**

Add to `LookupResponse`:
```python
context: str | None = Field(
    default=None,
    description="Optional context originally submitted with the resolution request.",
)
```

Add to `BulkLookupResult` (in the success fields block):
```python
context: str | None = Field(
    default=None,
    description="Optional context originally submitted with the resolution request.",
)
```

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/unit/ers_rest_api/domain/ -v
```
Expected: ALL PASS. All existing tests that construct these models without `context` still pass (optional field). The `_check_success_xor_error` validator is unaffected.

- [ ] **Step 5: Commit**

```bash
git add src/ers/ers_rest_api/domain/lookup.py tests/unit/ers_rest_api/domain/test_dto_validators.py
git commit -m "feat(ers-rest-api): add optional context field to LookupResponse and BulkLookupResult"
```

---

## Task 4 — Repository: `find_contexts_by_triads` batch query

**Files:**
- Modify: `src/ers/request_registry/adapters/records_repository.py`
- Test: `tests/unit/request_registry/adapters/test_records_repository.py`

The MongoDB document root already has `context` as a top-level field (stored via `model_dump()` on `ResolutionRequestRecord`).

- [ ] **Step 1: Write the failing tests** (add new class; reuse the `_async_iter` helper already in the file)

```python
class TestFindContextsByTriads:
    async def test_returns_empty_dict_for_empty_input(
        self, repo, async_collection
    ) -> None:
        result = await repo.find_contexts_by_triads([])
        assert result == {}
        async_collection.find.assert_not_called()

    async def test_returns_context_for_known_triad(
        self, repo, async_collection
    ) -> None:
        ident = EntityMentionIdentifier(
            source_id="S", request_id="R", entity_type="ORGANISATION"
        )
        triad_id = repo._triad_id(ident)
        async_collection.find.return_value = _async_iter(
            [{"_id": triad_id, "context": "procurement ctx"}]
        )
        result = await repo.find_contexts_by_triads([ident])
        assert result[("S", "R", "ORGANISATION")] == "procurement ctx"

    async def test_returns_none_for_absent_context_field(
        self, repo, async_collection
    ) -> None:
        ident = EntityMentionIdentifier(
            source_id="S", request_id="R", entity_type="ORGANISATION"
        )
        triad_id = repo._triad_id(ident)
        async_collection.find.return_value = _async_iter(
            [{"_id": triad_id}]   # old record — no context stored
        )
        result = await repo.find_contexts_by_triads([ident])
        assert result[("S", "R", "ORGANISATION")] is None

    async def test_queries_with_id_in(
        self, repo, async_collection
    ) -> None:
        ident = EntityMentionIdentifier(
            source_id="S", request_id="R", entity_type="ORGANISATION"
        )
        async_collection.find.return_value = _async_iter([])
        await repo.find_contexts_by_triads([ident])
        call_args = async_collection.find.call_args
        assert "$in" in call_args[0][0]["_id"]

    async def test_projects_only_id_and_context(
        self, repo, async_collection
    ) -> None:
        ident = EntityMentionIdentifier(
            source_id="S", request_id="R", entity_type="ORGANISATION"
        )
        async_collection.find.return_value = _async_iter([])
        await repo.find_contexts_by_triads([ident])
        call_args = async_collection.find.call_args
        # projection is second positional arg
        projection = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["projection"]
        assert projection == {"_id": 1, "context": 1}
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/unit/request_registry/adapters/test_records_repository.py -v
```
Expected: FAIL — method not found

- [ ] **Step 3: Implement**

Abstract method in `ResolutionRequestRepository`:
```python
@abstractmethod
async def find_contexts_by_triads(
    self, identifiers: list[EntityMentionIdentifier]
) -> dict[tuple[str, str, str], str | None]:
    """Return {(source_id, request_id, entity_type): context} for a batch of triads."""
```

Implementation in `MongoResolutionRequestRepository`:
```python
async def find_contexts_by_triads(
    self, identifiers: list[EntityMentionIdentifier]
) -> dict[tuple[str, str, str], str | None]:
    if not identifiers:
        return {}
    id_to_tuple: dict[str, tuple[str, str, str]] = {
        self._triad_id(i): (i.source_id, i.request_id, str(i.entity_type))
        for i in identifiers
    }
    cursor = self._collection.find(
        {"_id": {"$in": list(id_to_tuple.keys())}},
        {"_id": 1, "context": 1},
    )
    result: dict[tuple[str, str, str], str | None] = {}
    async for doc in cursor:
        key = id_to_tuple[doc["_id"]]
        result[key] = doc.get("context")
    return result
```

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/unit/request_registry/adapters/test_records_repository.py -v
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/ers/request_registry/adapters/records_repository.py \
        tests/unit/request_registry/adapters/test_records_repository.py
git commit -m "feat(request-registry): add find_contexts_by_triads batch query to repository"
```

---

## Task 5 — Service: `RequestRegistryService` exposes `get_contexts_for_triads`

**Files:**
- Modify: `src/ers/request_registry/services/request_registry_service.py`
- Test: `tests/unit/request_registry/services/test_request_registry_service.py`

- [ ] **Step 1: Write the failing tests** (add new class)

```python
class TestGetContextsForTriads:
    async def test_delegates_to_repo(
        self, service, resolution_repo
    ) -> None:
        ident = EntityMentionIdentifier(
            source_id="S", request_id="R", entity_type="ORGANISATION"
        )
        expected = {("S", "R", "ORGANISATION"): "some ctx"}
        resolution_repo.find_contexts_by_triads.return_value = expected

        result = await service.get_contexts_for_triads([ident])

        assert result == expected
        resolution_repo.find_contexts_by_triads.assert_awaited_once_with([ident])

    async def test_returns_empty_for_empty_input(
        self, service, resolution_repo
    ) -> None:
        resolution_repo.find_contexts_by_triads.return_value = {}
        result = await service.get_contexts_for_triads([])
        assert result == {}
```

Also add a test verifying context flows through `register_resolution_request`:
```python
class TestRegisterContextFlow:
    async def test_context_stored_when_mention_has_context(
        self, service, resolution_repo, mock_mention_parser
    ) -> None:
        resolution_repo.find_by_triad.return_value = None
        resolution_repo.store.side_effect = lambda r: r
        mention = EntityMention(
            identifiedBy=EntityMentionIdentifier(
                source_id="S", request_id="R", entity_type="ORGANISATION"
            ),
            content='{"name": "Acme"}',
            content_type="application/ld+json",
            context="procurement round 3",
        )

        result = await service.register_resolution_request(mention)

        assert result.context == "procurement round 3"
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/unit/request_registry/services/test_request_registry_service.py -v
```
Expected: `TestGetContextsForTriads` FAILs (method missing); `TestRegisterContextFlow` PASSes (erspec already provides it)

- [ ] **Step 3: Implement — add `get_contexts_for_triads` to `RequestRegistryService`**

```python
async def get_contexts_for_triads(
    self, identifiers: list[EntityMentionIdentifier]
) -> dict[tuple[str, str, str], str | None]:
    """Return context values for a batch of mention triads.

    Args:
        identifiers: The list of triads to look up.

    Returns:
        A dict mapping (source_id, request_id, entity_type) to the stored
        context, or None if the field is absent on the record.
    """
    return await self._resolution_repo.find_contexts_by_triads(identifiers)
```

Also add the `@trace_function`-decorated public API wrapper at the bottom of the file:
```python
@trace_function(span_name="request_registry.get_contexts_for_triads")
async def get_contexts_for_triads(
    identifiers: list[EntityMentionIdentifier],
    service: RequestRegistryService,
) -> dict[tuple[str, str, str], str | None]:
    """Return context values for a batch of mention triads."""
    return await service.get_contexts_for_triads(identifiers)
```

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/unit/request_registry/ -v
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/ers/request_registry/services/request_registry_service.py \
        tests/unit/request_registry/services/test_request_registry_service.py
git commit -m "feat(request-registry): add get_contexts_for_triads service method"
```

---

## Task 6 — `LookupService` fetches and returns context for `/lookup` and `/lookup-bulk`

**Files:**
- Modify: `src/ers/ers_rest_api/services/lookup_service.py`
- Test: `tests/unit/ers_rest_api/services/test_lookup_service.py`

`LookupService.handle_lookup` builds `LookupResponse` from a `Decision`. After getting the decision, it must also fetch context from the registry for that triad and include it in `LookupResponse`. `handle_bulk_lookup` calls `handle_lookup` per item, so context propagates automatically — just copy `lookup.context` into `BulkLookupResult`.

- [ ] **Step 1: Write the failing tests**

Add new import and fixture to `test_lookup_service.py`:
```python
from ers.request_registry.services.request_registry_service import RequestRegistryService

@pytest.fixture
def registry_service() -> AsyncMock:
    mock = create_autospec(RequestRegistryService, instance=True)
    mock.get_contexts_for_triads.return_value = {}
    return mock

# Update the service fixture to inject registry_service
@pytest.fixture
def service(coordinator: AsyncMock, registry_service: AsyncMock) -> LookupService:
    return LookupService(
        resolution_coordinator=coordinator,
        registry_service=registry_service,
    )
```

Add to the lookup test class:
```python
async def test_context_included_when_registry_returns_it(
    self, service, coordinator, registry_service
) -> None:
    coordinator.lookup_by_triad.return_value = _make_decision(IDENT, "cluster-010")
    registry_service.get_contexts_for_triads.return_value = {
        (IDENT.source_id, IDENT.request_id, str(IDENT.entity_type)): "procurement ctx"
    }

    result = await service.handle_lookup(IDENT.source_id, IDENT.request_id, IDENT.entity_type)

    assert result.context == "procurement ctx"

async def test_context_is_none_when_not_in_registry(
    self, service, coordinator, registry_service
) -> None:
    coordinator.lookup_by_triad.return_value = _make_decision(IDENT, "cluster-010")
    registry_service.get_contexts_for_triads.return_value = {}

    result = await service.handle_lookup(IDENT.source_id, IDENT.request_id, IDENT.entity_type)

    assert result.context is None
```

Add to the bulk lookup test class:
```python
async def test_context_propagates_into_bulk_result(
    self, service, coordinator, registry_service
) -> None:
    coordinator.lookup_by_triad.return_value = _make_decision(IDENT, "cluster-010")
    registry_service.get_contexts_for_triads.return_value = {
        (IDENT.source_id, IDENT.request_id, str(IDENT.entity_type)): "bulk ctx"
    }

    result = await service.handle_bulk_lookup(
        BulkLookupRequest(mentions=[LookupRequest(identified_by=IDENT)])
    )

    assert result.results[0].context == "bulk ctx"
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/unit/ers_rest_api/services/test_lookup_service.py -v
```
Expected: FAIL — `LookupService.__init__` does not accept `registry_service`

- [ ] **Step 3: Implement `lookup_service.py`**

```python
from ers.request_registry.services.request_registry_service import RequestRegistryService

class LookupService:
    def __init__(
        self,
        resolution_coordinator: ResolutionCoordinatorService,
        registry_service: RequestRegistryService,
    ) -> None:
        self._coordinator = resolution_coordinator
        self._registry_service = registry_service

    async def handle_lookup(
        self,
        source_id: str,
        request_id: str,
        entity_type: str,
    ) -> LookupResponse:
        """Look up the current cluster assignment for a mention triad."""
        identifier = EntityMentionIdentifier(
            source_id=source_id,
            request_id=request_id,
            entity_type=entity_type,
        )
        decision = await self._coordinator.lookup_by_triad(identifier)

        if decision is None:
            raise MentionNotFoundError(source_id, request_id, entity_type)

        contexts = await self._registry_service.get_contexts_for_triads([identifier])
        context = contexts.get((source_id, request_id, str(entity_type)))

        return LookupResponse(
            identified_by=decision.about_entity_mention,
            cluster_reference=decision.current_placement,
            last_updated=decision.updated_at or decision.created_at,
            context=context,
        )

    async def handle_bulk_lookup(self, request: BulkLookupRequest) -> BulkLookupResponse:
        """Look up cluster assignments for multiple mentions, collecting per-item results."""
        results: list[BulkLookupResult] = []
        for item in request.mentions:
            ident = item.identified_by
            try:
                lookup = await self.handle_lookup(
                    source_id=ident.source_id,
                    request_id=ident.request_id,
                    entity_type=ident.entity_type,
                )
                results.append(
                    BulkLookupResult(
                        identified_by=lookup.identified_by,
                        cluster_reference=lookup.cluster_reference,
                        last_updated=lookup.last_updated,
                        context=lookup.context,
                    )
                )
            except MentionNotFoundError:
                results.append(
                    BulkLookupResult(
                        identified_by=ident,
                        error=ErrorResponse(
                            error_code=ErrorCode.MENTION_NOT_FOUND,
                            detail=f"Mention ({ident.source_id}, {ident.request_id}, "
                            f"{ident.entity_type}) not found",
                        ),
                    )
                )
            except Exception:  # pylint: disable=broad-exception-caught
                results.append(
                    BulkLookupResult(
                        identified_by=ident,
                        error=ErrorResponse(
                            error_code=ErrorCode.SERVICE_ERROR,
                            detail=f"Failed to look up mention ({ident.source_id}, "
                            f"{ident.request_id}, {ident.entity_type})",
                        ),
                    )
                )
        return BulkLookupResponse(results=results)
```

Note: `handle_bulk_lookup` makes one registry call per item via `handle_lookup`. The current design is already sequential per-item, so this is consistent. A batch optimization is possible but out of scope.

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/unit/ers_rest_api/services/test_lookup_service.py -v
```
Expected: ALL PASS (set `registry_service.get_contexts_for_triads.return_value = {}` default in fixture to protect existing tests)

- [ ] **Step 5: Commit**

```bash
git add src/ers/ers_rest_api/services/lookup_service.py \
        tests/unit/ers_rest_api/services/test_lookup_service.py
git commit -m "feat(ers-rest-api): add context to /lookup and /lookup-bulk responses"
```

---

## Task 7 — `RefreshBulkService` enriches deltas with context

**Files:**
- Modify: `src/ers/ers_rest_api/services/refresh_bulk_service.py`
- Test: `tests/unit/ers_rest_api/services/test_refresh_bulk_service.py`

- [ ] **Step 1: Update the test fixtures and write failing tests**

Add new import and fixtures (the existing `service` fixture changes signature):
```python
from ers.request_registry.services.request_registry_service import RequestRegistryService

@pytest.fixture
def registry_service() -> AsyncMock:
    mock = create_autospec(RequestRegistryService, instance=True)
    mock.get_contexts_for_triads.return_value = {}   # safe default for all existing tests
    return mock

@pytest.fixture
def service(bulk_coordinator: AsyncMock, registry_service: AsyncMock) -> RefreshBulkService:
    return RefreshBulkService(
        bulk_coordinator=bulk_coordinator,
        registry_service=registry_service,
    )
```

Add new test class:
```python
class TestRefreshBulkServiceContext:
    async def test_context_in_delta_when_registry_returns_it(
        self, service, bulk_coordinator, registry_service
    ) -> None:
        decision = _make_decision(
            "SYSTEM_C", "req-001", "cluster-010", datetime(2026, 3, 15, tzinfo=UTC)
        )
        bulk_coordinator.refresh_bulk.return_value = CursorPage(
            results=[decision], count=1, next_cursor=None
        )
        registry_service.get_contexts_for_triads.return_value = {
            ("SYSTEM_C", "req-001", "ORGANISATION"): "procurement ctx"
        }

        result = await service.handle_refresh_bulk(
            RefreshBulkRequest(source_id="SYSTEM_C", limit=1000)
        )

        assert result.deltas[0].context == "procurement ctx"

    async def test_context_is_none_when_triad_not_in_registry(
        self, service, bulk_coordinator, registry_service
    ) -> None:
        decision = _make_decision(
            "SYSTEM_C", "req-001", "cluster-010", datetime(2026, 3, 15, tzinfo=UTC)
        )
        bulk_coordinator.refresh_bulk.return_value = CursorPage(
            results=[decision], count=1, next_cursor=None
        )
        registry_service.get_contexts_for_triads.return_value = {}

        result = await service.handle_refresh_bulk(
            RefreshBulkRequest(source_id="SYSTEM_C", limit=1000)
        )

        assert result.deltas[0].context is None

    async def test_get_contexts_called_with_decision_identifiers(
        self, service, bulk_coordinator, registry_service
    ) -> None:
        decision = _make_decision(
            "SYSTEM_C", "req-001", "cluster-010", datetime(2026, 3, 15, tzinfo=UTC)
        )
        bulk_coordinator.refresh_bulk.return_value = CursorPage(
            results=[decision], count=1, next_cursor=None
        )

        await service.handle_refresh_bulk(
            RefreshBulkRequest(source_id="SYSTEM_C", limit=1000)
        )

        identifiers_passed = registry_service.get_contexts_for_triads.call_args[0][0]
        assert decision.about_entity_mention in identifiers_passed

    async def test_empty_delta_calls_registry_with_empty_list(
        self, service, bulk_coordinator, registry_service
    ) -> None:
        bulk_coordinator.refresh_bulk.return_value = CursorPage(
            results=[], count=0, next_cursor=None
        )

        await service.handle_refresh_bulk(
            RefreshBulkRequest(source_id="SYSTEM_C", limit=1000)
        )

        registry_service.get_contexts_for_triads.assert_awaited_once_with([])
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/unit/ers_rest_api/services/test_refresh_bulk_service.py -v
```
Expected: FAIL — `RefreshBulkService.__init__` does not accept `registry_service`

- [ ] **Step 3: Implement `refresh_bulk_service.py`**

```python
"""Orchestrator for the POST /refresh-bulk endpoint."""

from erspec.models.core import Decision

from ers.ers_rest_api.domain.lookup import (
    LookupResponse,
    RefreshBulkRequest,
    RefreshBulkResponse,
)
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_coordinator.services.bulk_refresh_coordinator_service import (
    BulkRefreshCoordinatorService,
)


class RefreshBulkService:  # pylint: disable=too-few-public-methods
    """Orchestrator for the POST /refresh-bulk endpoint.

    Delegates to BulkRefreshCoordinatorService (Spine C) and maps
    the CursorPage[Decision] result to the REST API response DTO,
    enriching each delta with the context from the request registry.
    """

    def __init__(
        self,
        bulk_coordinator: BulkRefreshCoordinatorService,
        registry_service: RequestRegistryService,
    ) -> None:
        self._coordinator = bulk_coordinator
        self._registry_service = registry_service

    async def handle_refresh_bulk(self, request: RefreshBulkRequest) -> RefreshBulkResponse:
        """Retrieve delta of changed assignments since the last synchronisation snapshot."""
        page = await self._coordinator.refresh_bulk(
            source_id=request.source_id,
            cursor=request.continuation_cursor,
            page_size=request.limit,
        )

        identifiers = [d.about_entity_mention for d in page.results]
        contexts = await self._registry_service.get_contexts_for_triads(identifiers)

        def _ctx(d: Decision) -> str | None:
            key = (
                d.about_entity_mention.source_id,
                d.about_entity_mention.request_id,
                str(d.about_entity_mention.entity_type),
            )
            return contexts.get(key)

        deltas = [
            LookupResponse(
                identified_by=d.about_entity_mention,
                cluster_reference=d.current_placement,
                last_updated=d.updated_at or d.created_at,
                context=_ctx(d),
            )
            for d in page.results
        ]

        return RefreshBulkResponse(
            deltas=deltas,
            has_more=page.next_cursor is not None,
            continuation_cursor=page.next_cursor,
        )
```

- [ ] **Step 4: Run to verify pass**

```bash
poetry run pytest tests/unit/ers_rest_api/services/test_refresh_bulk_service.py -v
```
Expected: ALL PASS (including all pre-existing tests — `registry_service.get_contexts_for_triads.return_value = {}` default prevents breakage)

- [ ] **Step 5: Commit**

```bash
git add src/ers/ers_rest_api/services/refresh_bulk_service.py \
        tests/unit/ers_rest_api/services/test_refresh_bulk_service.py
git commit -m "feat(ers-rest-api): enrich refresh-bulk deltas with context from request registry"
```

---

## Task 8 — DI wiring + HTTP JSON verification

**Files:**
- Modify: `src/ers/ers_rest_api/entrypoints/api/dependencies.py`
- Test: `tests/unit/ers_rest_api/api/test_refresh_bulk.py`, `tests/unit/ers_rest_api/api/test_lookup.py`

- [ ] **Step 1: Write the tests** — add to `TestRefreshBulkEndpoint` and `TestLookupEndpoint` (all should pass immediately since conftests override the service mocks)

```python
async def test_context_field_in_delta_json_response(
    self, client, refresh_bulk_service
) -> None:
    refresh_bulk_service.handle_refresh_bulk.return_value = RefreshBulkResponse(
        deltas=[
            LookupResponse(
                identified_by=EntityMentionIdentifier(
                    source_id="SYSTEM_C",
                    request_id="req-001",
                    entity_type="ORGANISATION",
                ),
                cluster_reference=ClusterReference(
                    cluster_id="cluster-010",
                    confidence_score=0.9,
                    similarity_score=0.85,
                ),
                last_updated=datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC),
                context="procurement round 3",
            ),
        ],
        has_more=False,
        continuation_cursor=None,
    )
    response = await client.post("/api/v1/refresh-bulk", json=VALID_REFRESH_BULK_PAYLOAD)
    assert response.status_code == 200
    assert response.json()["deltas"][0]["context"] == "procurement round 3"

async def test_context_null_in_delta_json_when_absent(
    self, client, refresh_bulk_service
) -> None:
    refresh_bulk_service.handle_refresh_bulk.return_value = RefreshBulkResponse(
        deltas=[
            LookupResponse(
                identified_by=EntityMentionIdentifier(
                    source_id="SYSTEM_C",
                    request_id="req-001",
                    entity_type="ORGANISATION",
                ),
                cluster_reference=ClusterReference(
                    cluster_id="cluster-010",
                    confidence_score=0.9,
                    similarity_score=0.85,
                ),
                last_updated=datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC),
            ),
        ],
        has_more=False,
        continuation_cursor=None,
    )
    response = await client.post("/api/v1/refresh-bulk", json=VALID_REFRESH_BULK_PAYLOAD)
    assert response.status_code == 200
    assert response.json()["deltas"][0]["context"] is None
```

Also add to `test_lookup.py` (`TestLookupEndpoint`):
```python
async def test_context_field_in_lookup_json_response(
    self, client, lookup_service
) -> None:
    lookup_service.handle_lookup.return_value = LookupResponse(
        identified_by=EntityMentionIdentifier(
            source_id="SYSTEM_A", request_id="req-001", entity_type="ORGANISATION"
        ),
        cluster_reference=ClusterReference(
            cluster_id="cluster-010", confidence_score=0.9, similarity_score=0.85
        ),
        last_updated=datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC),
        context="procurement round 3",
    )
    response = await client.get(
        "/api/v1/lookup",
        params={"source_id": "SYSTEM_A", "request_id": "req-001", "entity_type": "ORGANISATION"},
    )
    assert response.status_code == 200
    assert response.json()["context"] == "procurement round 3"
```

- [ ] **Step 2: Run to verify they pass** (JSON serialisation of `context` already works)

```bash
poetry run pytest tests/unit/ers_rest_api/api/test_refresh_bulk.py tests/unit/ers_rest_api/api/test_lookup.py -v
```
Expected: ALL PASS

- [ ] **Step 3: Update `dependencies.py`** — wire `registry_service` into both `get_lookup_service` and `get_refresh_bulk_service`

```python
async def get_lookup_service(
    coordinator: Annotated[
        ResolutionCoordinatorService, Depends(get_resolution_coordinator)
    ],
    registry: Annotated[RequestRegistryService, Depends(_get_request_registry_service)],
) -> LookupService:
    return LookupService(resolution_coordinator=coordinator, registry_service=registry)

async def get_refresh_bulk_service(
    coordinator: Annotated[
        BulkRefreshCoordinatorService, Depends(_get_bulk_refresh_coordinator)
    ],
    registry: Annotated[RequestRegistryService, Depends(_get_request_registry_service)],
) -> RefreshBulkService:
    return RefreshBulkService(bulk_coordinator=coordinator, registry_service=registry)
```

- [ ] **Step 4: Run full test suite**

```bash
make -f Makefile.dev test
```
Expected: ALL PASS — no regressions

- [ ] **Step 5: Commit**

```bash
git add src/ers/ers_rest_api/entrypoints/api/dependencies.py \
        tests/unit/ers_rest_api/api/test_refresh_bulk.py \
        tests/unit/ers_rest_api/api/test_lookup.py
git commit -m "feat(ers-rest-api): wire registry_service into lookup and refresh-bulk DI"
```

---

## Verification

Run the full test suite:
```bash
make -f Makefile.dev test
```

Manual smoke test (requires running stack):
```bash
# 1. Submit resolve with context inside mention
curl -X POST http://localhost:8000/api/v1/resolve \
  -H "Content-Type: application/json" \
  -d '{
    "mention": {
      "identifiedBy": {"source_id": "S1", "request_id": "R1", "entity_type": "ORGANISATION"},
      "content": "{\"name\":\"Acme\"}",
      "content_type": "application/ld+json",
      "context": "procurement round 3"
    }
  }'

# 2. Fetch refresh-bulk delta — expect context in response
curl -X POST http://localhost:8000/api/v1/refresh-bulk \
  -H "Content-Type: application/json" \
  -d '{"source_id": "S1", "limit": 10}'
# Expected: delta item with "context": "procurement round 3"
```

---

## Key Pitfalls

1. **`_async_iter` helper for repository tests**: `find_contexts_by_triads` uses `async for doc in cursor`. Tests must set `async_collection.find.return_value = _async_iter([...])`, not a plain list. The helper is already defined in `test_records_repository.py`.

2. **`str(entity_type)` key coercion**: Use `str(d.about_entity_mention.entity_type)` in `RefreshBulkService._ctx()` and in `find_contexts_by_triads`'s `id_to_tuple`. Use the same coercion in test assertions.

3. **`registry_service.get_contexts_for_triads.return_value = {}`**: Set this on the fixture mock to prevent all pre-existing `test_refresh_bulk_service.py` tests from breaking when the fixture gains the new `registry_service` parameter.

4. **`create_autospec(RefreshBulkService, instance=True)`** in `conftest.py` — mocks the instance, not the constructor. The API-layer unit tests are unaffected by the constructor signature change.

5. **`context` field in MongoDB projection is top-level** (`"context": 1`), not nested. It is stored as a direct field of the `ResolutionRequestRecord` document because `EntityMention.context` is a flat Pydantic field.
