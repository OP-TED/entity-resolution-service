from datetime import datetime, timezone
from unittest.mock import AsyncMock

from fastapi import FastAPI
from httpx import AsyncClient

from ers.application.auth_dtos import UserContext, UserResponse
from ers.application.dtos import PaginatedResult
from ers.entrypoints.api.auth import get_current_user

USERS_URL = "/api/v1/users"


class TestCreateUser:
    async def test_admin_can_create_user(
        self,
        client: AsyncClient,
        user_management_service: AsyncMock,
    ) -> None:
        user_management_service.create_user.return_value = UserResponse(
            id="u-new",
            email="new@example.com",
            is_active=True,
            is_superuser=False,
            is_verified=False,
            created_at=datetime.now(timezone.utc),
        )

        response = await client.post(
            USERS_URL,
            json={"email": "new@example.com", "password": "securepassword"},
        )

        assert response.status_code == 201
        assert response.json()["email"] == "new@example.com"

    async def test_non_admin_gets_403(
        self,
        app: FastAPI,
    ) -> None:
        regular = UserContext(
            id="u-2",
            email="regular@example.com",
            is_superuser=False,
            is_verified=True,
        )
        app.dependency_overrides[get_current_user] = lambda: regular

        from httpx import ASGITransport
        from httpx import AsyncClient as AC

        async with AC(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.post(
                USERS_URL,
                json={"email": "x@example.com", "password": "securepassword"},
            )

        assert response.status_code == 403


class TestListUsers:
    async def test_admin_can_list_users(
        self,
        client: AsyncClient,
        user_management_service: AsyncMock,
    ) -> None:
        user_management_service.list_users.return_value = PaginatedResult(
            count=1,
            previous=None,
            next=None,
            results=[
                UserResponse(
                    id="u-1",
                    email="a@example.com",
                    is_active=True,
                    is_superuser=False,
                    is_verified=True,
                    created_at=datetime.now(timezone.utc),
                ),
            ],
        )

        response = await client.get(f"{USERS_URL}?page=2&per_page=5")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert len(data["results"]) == 1
        pagination = user_management_service.list_users.call_args.args[0]
        assert pagination.page == 2
        assert pagination.per_page == 5

    async def test_non_admin_gets_403(
        self,
        app: FastAPI,
    ) -> None:
        regular_user = UserContext(
            id="u-2",
            email="regular@example.com",
            is_superuser=False,
            is_verified=True,
        )
        app.dependency_overrides[get_current_user] = lambda: regular_user

        from httpx import ASGITransport
        from httpx import AsyncClient as AC

        async with AC(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.get(USERS_URL)

        assert response.status_code == 403


class TestPatchUser:
    async def test_admin_can_patch_user(
        self,
        client: AsyncClient,
        user_management_service: AsyncMock,
    ) -> None:
        user_management_service.patch_user.return_value = UserResponse(
            id="u-1",
            email="a@example.com",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            created_at=datetime.now(timezone.utc),
        )

        response = await client.patch(
            f"{USERS_URL}/u-1",
            json={"is_verified": True},
        )

        assert response.status_code == 200
        assert response.json()["is_verified"] is True


class TestDeleteUser:
    async def test_admin_can_delete_user(
        self,
        client: AsyncClient,
        user_management_service: AsyncMock,
    ) -> None:
        user_management_service.delete_user.return_value = None

        response = await client.delete(f"{USERS_URL}/u-1")

        assert response.status_code == 204
        assert response.content == b""

    async def test_non_admin_gets_403(
        self,
        app: FastAPI,
    ) -> None:
        regular = UserContext(
            id="u-2",
            email="regular@example.com",
            is_superuser=False,
            is_verified=True,
        )
        app.dependency_overrides[get_current_user] = lambda: regular

        from httpx import ASGITransport
        from httpx import AsyncClient as AC

        async with AC(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.delete(f"{USERS_URL}/u-1")

        assert response.status_code == 403
