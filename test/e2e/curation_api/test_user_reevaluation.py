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
        ClusterReference(
            cluster_id=cid, confidence_score=0.9 - i * 0.1, similarity_score=0.8
        )
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
    decision_repository.record_review = AsyncMock()
    decision_repository.find_review_metadata = AsyncMock(return_value={})
    user_action_service = UserActionService(
        user_action_repository=user_action_repository,
        entity_mention_repository=entity_mention_repository,
        user_repository=MagicMock(),
        decision_repository=decision_repository,
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
    entity_mention_repo = create_autospec(
        EntityMentionCurationRepository, instance=True
    )
    user_action_repo = create_autospec(UserActionCurationRepository, instance=True)
    ere_adapter = create_autospec(AbstractClient, instance=True)

    decision_repo.find_by_id = AsyncMock(return_value=decision)
    entity_mention_repo.find_by_identifiers = AsyncMock(return_value=[entity_mention])
    user_action_repo.has_current_action = AsyncMock(return_value=False)
    user_action_repo.save = AsyncMock()
    ere_adapter.push_request = AsyncMock(return_value=1)
    ere_adapter.request_channel_id = "ere_requests"

    service, _ = _build_service(
        decision_repo, entity_mention_repo, user_action_repo, ere_adapter
    )
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
    published = ere_adapter.push_request.call_args.args[0]
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
    entity_mention_repo = create_autospec(
        EntityMentionCurationRepository, instance=True
    )
    user_action_repo = create_autospec(UserActionCurationRepository, instance=True)
    ere_adapter = create_autospec(AbstractClient, instance=True)

    decision_repo.find_by_id = AsyncMock(return_value=decision)
    entity_mention_repo.find_by_identifiers = AsyncMock(return_value=[entity_mention])
    user_action_repo.has_current_action = AsyncMock(return_value=False)
    user_action_repo.save = AsyncMock()
    ere_adapter.push_request = AsyncMock(return_value=1)
    ere_adapter.request_channel_id = "ere_requests"

    service, _ = _build_service(
        decision_repo, entity_mention_repo, user_action_repo, ere_adapter
    )
    app = _build_app(service)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"{_API_PREFIX}/curation/decisions/{decision_id}/reject"
        )

    assert response.status_code == 204
    ere_adapter.push_request.assert_awaited_once()
    published = ere_adapter.push_request.call_args.args[0]
    assert published.entity_mention == entity_mention
    assert set(published.excluded_cluster_ids) == set(cluster_ids)
    assert published.proposed_cluster_ids == []
