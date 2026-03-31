from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fastapi import FastAPI
from httpx import AsyncClient

from ers.commons.domain.data_transfer_objects import CursorPage, PaginatedResult
from ers.commons.services.exceptions import NotFoundError
from ers.curation.domain.data_transfer_objects import (
    CanonicalEntityPreview,
    EntityMentionPreview,
    UserActionSummary,
)
from ers.curation.entrypoints.api.auth import get_current_user
from ers.users.domain.data_transfer_objects import UserContext
from tests.unit.factories import UserActionFactory

USER_ACTIONS_URL = "/api/v1/user-actions"


class TestListUserActions:
    async def test_admin_can_list_cursor_paginated_user_actions(
        self,
        client: AsyncClient,
        user_action_service: AsyncMock,
    ) -> None:
        action = UserActionFactory.build(created_at=datetime.now(UTC))
        mention_preview = EntityMentionPreview(
            identified_by=action.about_entity_mention,
            parsed_representation='{"name": "Example Entity"}',
        )
        user_action_service.list_user_actions.return_value = CursorPage(
            results=[
                UserActionSummary(
                    id=action.id,
                    about_entity_mention=mention_preview,
                    candidates=action.candidates,
                    selected_cluster=action.selected_cluster,
                    action_type=action.action_type,
                    actor=action.actor,
                    created_at=action.created_at,
                    metadata=action.metadata,
                )
            ],
            next_cursor=None,
        )

        response = await client.get(f"{USER_ACTIONS_URL}?limit=5")

        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["id"] == action.id
        assert data["results"][0]["about_entity_mention"]["identified_by"] == (
            action.about_entity_mention.model_dump(mode="json")
        )
        assert data["results"][0]["about_entity_mention"]["parsed_representation"] == {
            "name": "Example Entity"
        }
        assert data["next_cursor"] is None
        user_action_service.list_user_actions.assert_called_once()
        cursor_params = user_action_service.list_user_actions.call_args.args[0]
        assert cursor_params.limit == 5

    async def test_passes_filters_when_query_params_provided(
        self,
        client: AsyncClient,
        user_action_service: AsyncMock,
    ) -> None:
        user_action_service.list_user_actions.return_value = CursorPage(
            results=[], next_cursor=None
        )

        response = await client.get(
            USER_ACTIONS_URL,
            params={"actor": "curator@test.com", "ordering": "created_at"},
        )

        assert response.status_code == 200
        user_action_service.list_user_actions.assert_called_once()
        filters = user_action_service.list_user_actions.call_args.args[1]
        assert filters is not None
        assert filters.actor == "curator@test.com"
        assert filters.ordering is not None

    async def test_non_admin_gets_403(
        self,
        app: FastAPI,
    ) -> None:
        regular_user = UserContext(
            id="u-2",
            email="regular@example.com",
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        app.dependency_overrides[get_current_user] = lambda: regular_user

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.get(USER_ACTIONS_URL)

        assert response.status_code == 403


class TestGetSelectedCluster:
    async def test_returns_selected_cluster_preview(
        self,
        client: AsyncClient,
        user_action_service: AsyncMock,
        canonical_entity_service: AsyncMock,
    ) -> None:
        preview = CanonicalEntityPreview(
            cluster_id="cluster-1",
            confidence_score=0.95,
            similarity_score=0.9,
            top_entities=[],
        )
        user_action_service.get_selected_cluster_preview.return_value = preview

        response = await client.get(f"{USER_ACTIONS_URL}/action-1/selected-cluster")

        assert response.status_code == 200
        data = response.json()
        assert data["cluster_id"] == "cluster-1"
        assert data["confidence_score"] == 0.95
        user_action_service.get_selected_cluster_preview.assert_called_once()

    async def test_not_found(
        self,
        client: AsyncClient,
        user_action_service: AsyncMock,
    ) -> None:
        user_action_service.get_selected_cluster_preview.side_effect = NotFoundError(
            "UserAction", "action-1"
        )

        response = await client.get(f"{USER_ACTIONS_URL}/action-1/selected-cluster")

        assert response.status_code == 404

    async def test_returns_null_when_no_selected_cluster(
        self,
        client: AsyncClient,
        user_action_service: AsyncMock,
        canonical_entity_service: AsyncMock,
    ) -> None:
        user_action_service.get_selected_cluster_preview.return_value = None

        response = await client.get(f"{USER_ACTIONS_URL}/action-1/selected-cluster")

        assert response.status_code == 200
        assert response.json() is None

    async def test_non_admin_gets_403(
        self,
        app: FastAPI,
    ) -> None:
        regular_user = UserContext(
            id="u-2",
            email="regular@example.com",
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        app.dependency_overrides[get_current_user] = lambda: regular_user

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.get(f"{USER_ACTIONS_URL}/action-1/selected-cluster")

        assert response.status_code == 403


class TestGetCandidates:
    async def test_returns_paginated_candidates(
        self,
        client: AsyncClient,
        user_action_service: AsyncMock,
        canonical_entity_service: AsyncMock,
    ) -> None:
        preview = CanonicalEntityPreview(
            cluster_id="cluster-2",
            confidence_score=0.7,
            similarity_score=0.65,
            top_entities=[],
        )
        user_action_service.get_candidate_previews.return_value = PaginatedResult(
            count=1,
            previous=None,
            next=None,
            results=[preview],
        )

        response = await client.get(
            f"{USER_ACTIONS_URL}/action-1/candidates",
            params={"page": 1, "per_page": 10},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["cluster_id"] == "cluster-2"
        user_action_service.get_candidate_previews.assert_called_once()

    async def test_not_found(
        self,
        client: AsyncClient,
        user_action_service: AsyncMock,
    ) -> None:
        user_action_service.get_candidate_previews.side_effect = NotFoundError(
            "UserAction", "action-1"
        )

        response = await client.get(f"{USER_ACTIONS_URL}/action-1/candidates")

        assert response.status_code == 404

    async def test_non_admin_gets_403(
        self,
        app: FastAPI,
    ) -> None:
        regular_user = UserContext(
            id="u-2",
            email="regular@example.com",
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        app.dependency_overrides[get_current_user] = lambda: regular_user

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.get(f"{USER_ACTIONS_URL}/action-1/candidates")

        assert response.status_code == 403
