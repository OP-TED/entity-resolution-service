# Fix1 ERE Forwarding — Part 4: Create E2E Tests + Final Verification

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the two e2e test files whose names are the acceptance criteria. All six failing tests listed in the spec must pass.

**Architecture:** Each test file mounts the real curation FastAPI app via `ASGITransport` with a `_noop_lifespan` (no real MongoDB/Redis). Repositories are mocked via `create_autospec`. Auth is bypassed via `get_current_user` override. `EREPublishService` is a real instance backed by a mocked `AbstractClient` — this lets us inspect which Redis `push_request` calls were made.

**Tech Stack:** httpx `AsyncClient` + `ASGITransport`, pytest-asyncio, `create_autospec`, `AbstractClient`

---

## Failing Tests That Must Pass

```
tests/e2e/curation_api/test_user_reevaluation.py::test_placement_recommendation
tests/e2e/curation_api/test_user_reevaluation.py::test_exclusion_recommendation
tests/e2e/curation_api/test_bulk_reevaluation.py::test_bulk_placement_recommendation[2]
tests/e2e/curation_api/test_bulk_reevaluation.py::test_bulk_placement_recommendation[5]
tests/e2e/curation_api/test_bulk_reevaluation.py::test_bulk_placement_recommendation[10]
tests/e2e/curation_api/test_bulk_reevaluation.py::test_bulk_partial_success
```

---

## File Map

| File | Change |
|------|--------|
| `tests/e2e/curation_api/__init__.py` | Create (empty) |
| `tests/e2e/curation_api/test_user_reevaluation.py` | Create — single-decision tests |
| `tests/e2e/curation_api/test_bulk_reevaluation.py` | Create — bulk tests (parametrized) |

---

### Task 7: Create directory and shared helpers

**Files:**
- Create: `tests/e2e/curation_api/__init__.py`

- [ ] **Step 1: Create empty `__init__.py`**

```bash
touch tests/e2e/curation_api/__init__.py
```

---

### Task 8: Create `test_user_reevaluation.py`

**Files:**
- Create: `tests/e2e/curation_api/test_user_reevaluation.py`

- [ ] **Step 1: Write the full file**

```python
"""
E2E tests for single-decision curation re-evaluation ERE forwarding.

Tests UC-B2.1: after assign or reject, the service must publish the correct
EntityMentionResolutionRequest to the ere_requests queue.

ERE is mocked at the Redis adapter boundary (AbstractClient.push_request).
Repositories are mocked via create_autospec. No real MongoDB or Redis needed.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMention, EntityMentionIdentifier
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ers.commons.adapters.redis_client import AbstractClient
from ers.curation.adapters import (
    EntityMentionCurationRepository,
    UserActionCurationRepository,
)
from ers.curation.entrypoints.api.app import create_app
from ers.curation.entrypoints.api.auth import get_current_user
from ers.curation.entrypoints.api.dependencies import get_decision_curation_service
from ers.curation.services import DecisionCurationService, UserActionService
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from ers.resolution_decision_store.adapters.decision_repository import DecisionRepository
from ers.users.domain.data_transfer_objects import UserContext

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_PREFIX = "/api/v1"
_ACTOR = UserContext(
    id="curator-id",
    email="curator@test.com",
    is_active=True,
    is_superuser=False,
    is_verified=True,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_identifier(
    source_id: str = "src-001",
    request_id: str = "req-001",
    entity_type: str = "ORGANISATION",
) -> EntityMentionIdentifier:
    return EntityMentionIdentifier(
        source_id=source_id,
        request_id=request_id,
        entity_type=entity_type,
    )


def _make_entity_mention(identifier: EntityMentionIdentifier) -> EntityMention:
    return EntityMention(
        identifiedBy=identifier,
        content="<rdf/>",
        content_type="application/rdf+xml",
    )


def _make_decision(
    decision_id: str,
    identifier: EntityMentionIdentifier,
    cluster_ids: list[str] | None = None,
) -> Decision:
    if cluster_ids is None:
        cluster_ids = ["cl-001", "cl-002"]
    now = datetime.now(UTC)
    candidates = [
        ClusterReference(cluster_id=cid, confidence_score=0.9 - i * 0.1, similarity_score=0.8)
        for i, cid in enumerate(cluster_ids)
    ]
    return Decision(
        id=decision_id,
        about_entity_mention=identifier,
        current_placement=candidates[0],
        candidates=candidates,
        created_at=now,
        updated_at=now,
    )


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def _build_app(service: DecisionCurationService) -> FastAPI:
    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    app.dependency_overrides[get_decision_curation_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: _ACTOR
    return app


def _build_service(
    decision_repository: MagicMock,
    entity_mention_repository: MagicMock,
    user_action_repository: MagicMock,
    ere_adapter: MagicMock,
) -> tuple[DecisionCurationService, EREPublishService]:
    user_action_service = UserActionService(
        user_action_repository=user_action_repository,
        entity_mention_repository=entity_mention_repository,
        user_repository=MagicMock(),
    )
    ere_publish_service = EREPublishService(adapter=ere_adapter)
    service = DecisionCurationService(
        decision_repository=decision_repository,
        entity_mention_repository=entity_mention_repository,
        user_action_service=user_action_service,
        ere_publish_service=ere_publish_service,
    )
    return service, ere_publish_service


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_placement_recommendation() -> None:
    """POST /decisions/{id}/assign publishes resolveConsideringRecommendation to ERE."""
    decision_id = "decision-assign-001"
    identifier = _make_identifier()
    entity_mention = _make_entity_mention(identifier)
    decision = _make_decision(decision_id, identifier, cluster_ids=["cl-top", "cl-alt"])

    decision_repo = create_autospec(DecisionRepository, instance=True)
    entity_mention_repo = create_autospec(EntityMentionCurationRepository, instance=True)
    user_action_repo = create_autospec(UserActionCurationRepository, instance=True)
    ere_adapter = create_autospec(AbstractClient, instance=True)

    decision_repo.find_by_id = AsyncMock(return_value=decision)
    entity_mention_repo.find_by_identifiers = AsyncMock(return_value=[entity_mention])
    user_action_repo.has_current_action = AsyncMock(return_value=False)
    user_action_repo.save = AsyncMock()
    ere_adapter.push_request = AsyncMock(return_value=1)
    ere_adapter.request_channel_id = "ere_requests"

    service, _ = _build_service(decision_repo, entity_mention_repo, user_action_repo, ere_adapter)
    app = _build_app(service)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"{_API_PREFIX}/curation/decisions/{decision_id}/assign",
            json={"cluster_id": "cl-top"},
        )

    assert response.status_code == 204
    ere_adapter.push_request.assert_awaited_once()
    published = ere_adapter.push_request.call_args[0][0]
    assert published.entity_mention == entity_mention
    assert published.proposed_cluster_ids == ["cl-top"]
    assert published.excluded_cluster_ids == []


@pytest.mark.asyncio
async def test_exclusion_recommendation() -> None:
    """POST /decisions/{id}/reject publishes resolveWithExclusions to ERE."""
    decision_id = "decision-reject-001"
    identifier = _make_identifier()
    entity_mention = _make_entity_mention(identifier)
    cluster_ids = ["cl-001", "cl-002", "cl-003"]
    decision = _make_decision(decision_id, identifier, cluster_ids=cluster_ids)

    decision_repo = create_autospec(DecisionRepository, instance=True)
    entity_mention_repo = create_autospec(EntityMentionCurationRepository, instance=True)
    user_action_repo = create_autospec(UserActionCurationRepository, instance=True)
    ere_adapter = create_autospec(AbstractClient, instance=True)

    decision_repo.find_by_id = AsyncMock(return_value=decision)
    entity_mention_repo.find_by_identifiers = AsyncMock(return_value=[entity_mention])
    user_action_repo.has_current_action = AsyncMock(return_value=False)
    user_action_repo.save = AsyncMock()
    ere_adapter.push_request = AsyncMock(return_value=1)
    ere_adapter.request_channel_id = "ere_requests"

    service, _ = _build_service(decision_repo, entity_mention_repo, user_action_repo, ere_adapter)
    app = _build_app(service)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"{_API_PREFIX}/curation/decisions/{decision_id}/reject"
        )

    assert response.status_code == 204
    ere_adapter.push_request.assert_awaited_once()
    published = ere_adapter.push_request.call_args[0][0]
    assert published.entity_mention == entity_mention
    assert set(published.excluded_cluster_ids) == set(cluster_ids)
    assert published.proposed_cluster_ids == []
```

- [ ] **Step 2: Run to confirm both tests PASS**

```bash
poetry run pytest tests/e2e/curation_api/test_user_reevaluation.py -v 2>&1 | tail -15
```

Expected: `test_placement_recommendation` PASS, `test_exclusion_recommendation` PASS.

---

### Task 9: Create `test_bulk_reevaluation.py`

**Files:**
- Create: `tests/e2e/curation_api/test_bulk_reevaluation.py`

- [ ] **Step 1: Write the full file**

```python
"""
E2E tests for bulk curation re-evaluation ERE forwarding.

Tests UC-B2.2: bulk-accept and bulk-reject each produce one ERE message per mention.
Partial success: only found decisions produce ERE messages.

ERE is mocked at the Redis adapter boundary. No real MongoDB or Redis needed.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMention, EntityMentionIdentifier
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ers.commons.adapters.redis_client import AbstractClient
from ers.curation.adapters import (
    EntityMentionCurationRepository,
    UserActionCurationRepository,
)
from ers.curation.entrypoints.api.app import create_app
from ers.curation.entrypoints.api.auth import get_current_user
from ers.curation.entrypoints.api.dependencies import get_decision_curation_service
from ers.curation.services import DecisionCurationService, UserActionService
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from ers.resolution_decision_store.adapters.decision_repository import DecisionRepository
from ers.users.domain.data_transfer_objects import UserContext

pytestmark = pytest.mark.e2e

_API_PREFIX = "/api/v1"
_ACTOR = UserContext(
    id="curator-id",
    email="curator@test.com",
    is_active=True,
    is_superuser=False,
    is_verified=True,
)

# ---------------------------------------------------------------------------
# Helpers (duplicated from test_user_reevaluation for independence)
# ---------------------------------------------------------------------------


def _make_identifier(source_id: str, request_id: str) -> EntityMentionIdentifier:
    return EntityMentionIdentifier(
        source_id=source_id, request_id=request_id, entity_type="ORGANISATION"
    )


def _make_entity_mention(identifier: EntityMentionIdentifier) -> EntityMention:
    return EntityMention(
        identifiedBy=identifier,
        content="<rdf/>",
        content_type="application/rdf+xml",
    )


def _make_decision(decision_id: str, identifier: EntityMentionIdentifier) -> Decision:
    now = datetime.now(UTC)
    current = ClusterReference(cluster_id=f"cl-{decision_id}", confidence_score=0.9, similarity_score=0.8)
    return Decision(
        id=decision_id,
        about_entity_mention=identifier,
        current_placement=current,
        candidates=[current],
        created_at=now,
        updated_at=now,
    )


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def _build_app(service: DecisionCurationService) -> FastAPI:
    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    app.dependency_overrides[get_decision_curation_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: _ACTOR
    return app


def _build_service_with_decisions(
    decisions: list[Decision],
) -> tuple[DecisionCurationService, MagicMock]:
    """Build a service wired with mocked repos populated with given decisions."""
    decision_map = {d.id: d for d in decisions}
    identifier_map = {d.id: _make_entity_mention(d.about_entity_mention) for d in decisions}

    decision_repo = create_autospec(DecisionRepository, instance=True)
    entity_mention_repo = create_autospec(EntityMentionCurationRepository, instance=True)
    user_action_repo = create_autospec(UserActionCurationRepository, instance=True)
    ere_adapter = create_autospec(AbstractClient, instance=True)

    async def _find_by_id(decision_id: str) -> Decision | None:
        return decision_map.get(decision_id)

    async def _find_mentions(identifiers):
        return [
            identifier_map[d.id]
            for d in decisions
            if d.about_entity_mention in identifiers
        ]

    decision_repo.find_by_id = AsyncMock(side_effect=_find_by_id)
    entity_mention_repo.find_by_identifiers = AsyncMock(side_effect=_find_mentions)
    user_action_repo.has_current_action = AsyncMock(return_value=False)
    user_action_repo.save = AsyncMock()
    ere_adapter.push_request = AsyncMock(return_value=1)
    ere_adapter.request_channel_id = "ere_requests"

    user_action_service = UserActionService(
        user_action_repository=user_action_repo,
        entity_mention_repository=entity_mention_repo,
        user_repository=MagicMock(),
    )
    ere_publish_service = EREPublishService(adapter=ere_adapter)
    service = DecisionCurationService(
        decision_repository=decision_repo,
        entity_mention_repository=entity_mention_repo,
        user_action_service=user_action_service,
        ere_publish_service=ere_publish_service,
    )
    return service, ere_adapter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("n", [2, 5, 10])
async def test_bulk_placement_recommendation(n: int) -> None:
    """POST /decisions/bulk-accept produces N resolveConsideringRecommendation messages."""
    decisions = [
        _make_decision(f"dec-{i}", _make_identifier(f"src-{i}", f"req-{i}"))
        for i in range(n)
    ]
    service, ere_adapter = _build_service_with_decisions(decisions)
    app = _build_app(service)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"{_API_PREFIX}/curation/decisions/bulk-accept",
            json={"decision_ids": [d.id for d in decisions]},
        )

    assert response.status_code == 200
    data = response.json()
    assert all(r["status"] == "success" for r in data["results"])
    assert ere_adapter.push_request.await_count == n

    for call in ere_adapter.push_request.call_args_list:
        published = call[0][0]
        assert len(published.proposed_cluster_ids) == 1
        assert published.excluded_cluster_ids == []


@pytest.mark.asyncio
async def test_bulk_partial_success() -> None:
    """bulk-accept with some not-found IDs: ERE message sent only for found decisions."""
    found_decisions = [
        _make_decision("dec-found-1", _make_identifier("src-1", "req-1")),
        _make_decision("dec-found-2", _make_identifier("src-2", "req-2")),
    ]
    service, ere_adapter = _build_service_with_decisions(found_decisions)
    app = _build_app(service)

    all_ids = ["dec-found-1", "dec-found-2", "dec-missing-1"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"{_API_PREFIX}/curation/decisions/bulk-accept",
            json={"decision_ids": all_ids},
        )

    assert response.status_code == 200
    data = response.json()
    statuses = {r["decision_id"]: r["status"] for r in data["results"]}
    assert statuses["dec-found-1"] == "success"
    assert statuses["dec-found-2"] == "success"
    assert statuses["dec-missing-1"] == "not_found"

    # ERE published only for the two found decisions
    assert ere_adapter.push_request.await_count == 2
```

- [ ] **Step 2: Run the failing tests — confirm they now PASS**

```bash
poetry run pytest tests/e2e/curation_api/ -v 2>&1 | tail -20
```

Expected:
```
PASSED tests/e2e/curation_api/test_user_reevaluation.py::test_placement_recommendation
PASSED tests/e2e/curation_api/test_user_reevaluation.py::test_exclusion_recommendation
PASSED tests/e2e/curation_api/test_bulk_reevaluation.py::test_bulk_placement_recommendation[2]
PASSED tests/e2e/curation_api/test_bulk_reevaluation.py::test_bulk_placement_recommendation[5]
PASSED tests/e2e/curation_api/test_bulk_reevaluation.py::test_bulk_placement_recommendation[10]
PASSED tests/e2e/curation_api/test_bulk_reevaluation.py::test_bulk_partial_success
```

- [ ] **Step 3: Run full unit + feature suite to confirm no regressions**

```bash
poetry run pytest tests/unit/ tests/feature/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 4: Run e2e suite via make**

```bash
make test-e2e 2>&1 | tail -20
```

Expected: 6 new tests pass, all pre-existing e2e tests unaffected.

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/curation_api/
git commit -m "test(e2e): add curation API re-evaluation ERE forwarding tests (UC-B2.1, UC-B2.2)"
```

---

## Final Acceptance Check

Run the exact commands from the spec:

```bash
make up   # ensure docker-compose services are running
make test-e2e 2>&1 | grep -E "PASSED|FAILED|ERROR" | grep "curation_api"
```

All six lines must show `PASSED`. If any show `FAILED`:
1. Check import errors first (`python -c "from ers.curation.services import DecisionCurationService"`)
2. Check `ere_adapter.push_request` call count assertions — verify `_find_mentions` side-effect matches the identifiers correctly
3. Run with `-s` flag for detailed output: `poetry run pytest tests/e2e/curation_api/ -v -s`
