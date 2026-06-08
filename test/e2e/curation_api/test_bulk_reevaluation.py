"""
E2E tests for bulk curation re-evaluation ERE forwarding.

Tests UC-B2.2: bulk-accept produces one ERE message per mention.
Partial success: only found decisions produce ERE messages.

ERE is mocked at the Redis adapter boundary. No real MongoDB or Redis needed.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from erspec.models.core import (
    ClusterReference,
    Decision,
    EntityMention,
    EntityMentionIdentifier,
)
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
from ers.resolution_decision_store.adapters.decision_repository import (
    DecisionRepository,
)
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
    current = ClusterReference(
        cluster_id=f"cl-{decision_id}", confidence_score=0.9, similarity_score=0.8
    )
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
    identifier_map = {
        d.id: _make_entity_mention(d.about_entity_mention) for d in decisions
    }

    decision_repo = create_autospec(DecisionRepository, instance=True)
    entity_mention_repo = create_autospec(
        EntityMentionCurationRepository, instance=True
    )
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

    decision_repo.record_review = AsyncMock()
    decision_repo.find_review_metadata = AsyncMock(return_value={})
    user_action_service = UserActionService(
        user_action_repository=user_action_repo,
        entity_mention_repository=entity_mention_repo,
        user_repository=MagicMock(),
        decision_repository=decision_repo,
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
        published = call.args[0]
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
