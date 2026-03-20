from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fastapi import FastAPI
from httpx import AsyncClient

from ers.commons.domain.data_transfer_objects import PaginatedResult
from ers.curation.domain.data_transfer_objects import (
    EntityMentionPreview,
    UserActionSummary,
)
from ers.curation.entrypoints.api.auth import get_current_user
from ers.users.domain.data_transfer_objects import UserContext
from tests.unit.factories import UserActionFactory

USER_ACTIONS_URL = "/api/v1/user-actions"


class TestListUserActions:
    async def test_admin_can_list_paginated_user_actions(
        self,
        client: AsyncClient,
        user_action_service: AsyncMock,
    ) -> None:
        action = UserActionFactory.build(created_at=datetime.now(UTC))
        mention_preview = EntityMentionPreview(
            identified_by=action.about_entity_mention,
            parsed_representation='{"name": "Example Entity"}',
        )
        user_action_service.list_user_actions.return_value = PaginatedResult(
            count=1,
            previous=None,
            next=None,
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
        )

        response = await client.get(f"{USER_ACTIONS_URL}?page=2&per_page=5")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["id"] == action.id
        assert data["results"][0]["about_entity_mention"]["identified_by"] == (
            action.about_entity_mention.model_dump(mode="json")
        )
        assert data["results"][0]["about_entity_mention"]["parsed_representation"] == {
            "name": "Example Entity"
        }
        user_action_service.list_user_actions.assert_called_once()
        pagination = user_action_service.list_user_actions.call_args.args[0]
        assert pagination.page == 2
        assert pagination.per_page == 5

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
