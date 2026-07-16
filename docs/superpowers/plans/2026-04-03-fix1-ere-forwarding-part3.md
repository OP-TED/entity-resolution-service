# Fix1 ERE Forwarding — Part 3: Wire Redis + EREPublishService into Curation App

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The curation FastAPI app currently has no Redis client. Add it to the lifespan, expose it via a dependency provider, and wire it into `get_decision_curation_service`.

**Architecture:** Mirrors the pattern in `src/ers/ers_rest_api/entrypoints/api/app.py` — `RedisEREClient` created in lifespan, stored in `app.state.redis_client`, accessed via a dependency. The curation app only publishes (no response listener), so one client suffices.

**Tech Stack:** FastAPI lifespan, `RedisConnectionConfig`, `RedisEREClient`, `EREPublishService`

---

## File Map

| File | Change |
|------|--------|
| `src/ers/curation/entrypoints/api/app.py` | Add Redis client creation in `lifespan` |
| `src/ers/curation/entrypoints/api/dependencies.py` | Add `_get_redis_client`, `get_ere_publish_service`; update `get_decision_curation_service` |
| `tests/unit/curation/api/test_dependencies.py` | Verify `test_get_decision_curation_service` passes with new signature |

---

### Task 5: Add Redis client to curation app lifespan

**Files:**
- Modify: `src/ers/curation/entrypoints/api/app.py`

- [ ] **Step 1: Add imports**

Add to the import block in `app.py`:

```python
from ers.commons.adapters.redis_client import RedisConnectionConfig, RedisEREClient
```

- [ ] **Step 2: Update `lifespan` to create a Redis client**

Replace the existing `lifespan` function:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage MongoDB and Redis client lifecycle, and seed admin user."""
    # --- MongoDB ---
    manager = MongoClientManager(config.MONGO_URI, config.MONGO_DATABASE_NAME)
    await manager.connect()
    await manager.ensure_indexes()
    app.state.mongo_db = manager.get_database()

    # --- Redis (ERE publish only — no response listener) ---
    redis_config = RedisConnectionConfig.from_settings(config)
    redis_client = RedisEREClient(
        config_or_client=redis_config,
        request_channel=config.ERSYS_REQUEST_QUEUE,
        response_channel=config.ERSYS_RESPONSE_QUEUE,
    )
    app.state.redis_client = redis_client

    await _seed_admin_user(app.state.mongo_db)

    try:
        yield
    finally:
        await redis_client.close()
        await manager.close()
```

- [ ] **Step 3: Run unit tests — app module still importable**

```bash
poetry run pytest tests/unit/curation/ -v --collect-only 2>&1 | tail -10
```

Expected: collection succeeds (no import errors).

---

### Task 6: Add `get_ere_publish_service` dependency and update `get_decision_curation_service`

**Files:**
- Modify: `src/ers/curation/entrypoints/api/dependencies.py`

- [ ] **Step 1: Add imports**

Add to the import block:

```python
from ers.commons.adapters.redis_client import RedisEREClient
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
```

- [ ] **Step 2: Add `_get_redis_client` accessor**

After the `_get_database` function (around line 31), add:

```python
def _get_redis_client(request: Request) -> RedisEREClient:
    return cast(RedisEREClient, request.app.state.redis_client)
```

Add `cast` to the existing `typing` import if not already present:

```python
from typing import Annotated, Any, cast
```

- [ ] **Step 3: Add `get_ere_publish_service` provider**

After `get_statistics_repository` (around line 75), add:

```python
async def get_ere_publish_service(
    client: Annotated[RedisEREClient, Depends(_get_redis_client)],
) -> EREPublishService:
    return EREPublishService(adapter=client)
```

- [ ] **Step 4: Update `get_decision_curation_service`**

Replace the existing function (lines ~98–107):

```python
async def get_decision_curation_service(
    decision_repo: Annotated[DecisionRepository, Depends(get_decision_repository)],
    entity_repo: Annotated[EntityMentionCurationRepository, Depends(get_entity_mention_repository)],
    user_action_service: Annotated[UserActionService, Depends(get_user_action_service)],
    ere_publish_service: Annotated[EREPublishService, Depends(get_ere_publish_service)],
) -> DecisionCurationService:
    return DecisionCurationService(
        decision_repository=decision_repo,
        entity_mention_repository=entity_repo,
        user_action_service=user_action_service,
        ere_publish_service=ere_publish_service,
    )
```

- [ ] **Step 5: Run all unit tests**

```bash
poetry run pytest tests/unit/curation/ -v 2>&1 | tail -30
```

Expected: All unit curation tests pass including `test_get_decision_curation_service`.

- [ ] **Step 6: Check architecture**

```bash
poetry run lint-imports 2>&1 | tail -20
```

Expected: No new architecture violations (`curation` → `ere_contract_client` is Tier 3 → Tier 1, valid).

- [ ] **Step 7: Commit**

```bash
git add src/ers/curation/entrypoints/api/app.py \
        src/ers/curation/entrypoints/api/dependencies.py
git commit -m "feat(curation): wire EREPublishService into curation app lifespan and dependency graph"
```
