from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fastapi import FastAPI
from httpx import AsyncClient

from ers.commons.domain.data_transfer_objects import PaginatedResult
from ers.curation.entrypoints.api.auth import get_current_user
from ers.users.domain.data_transfer_objects import UserContext, UserResponse

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
            created_at=datetime.now(UTC),
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
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        app.dependency_overrides[get_current_user] = lambda: regular

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
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
                    created_at=datetime.now(UTC),
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

    async def test_verified_non_admin_can_list_users(
        self,
        app: FastAPI,
        user_management_service: AsyncMock,
    ) -> None:
        regular_user = UserContext(
            id="u-2",
            email="regular@example.com",
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        app.dependency_overrides[get_current_user] = lambda: regular_user
        user_management_service.list_users.return_value = PaginatedResult(
            count=0, previous=None, next=None, results=[]
        )

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.get(USERS_URL)

        assert response.status_code == 200

    async def test_unverified_gets_403(
        self,
        app: FastAPI,
    ) -> None:
        unverified_user = UserContext(
            id="u-3",
            email="unverified@example.com",
            is_active=True,
            is_superuser=False,
            is_verified=False,
        )
        app.dependency_overrides[get_current_user] = lambda: unverified_user

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.get(USERS_URL)

        assert response.status_code == 403

    async def test_passes_email_search_to_service(
        self,
        client: AsyncClient,
        user_management_service: AsyncMock,
    ) -> None:
        user_management_service.list_users.return_value = PaginatedResult(
            count=0, previous=None, next=None, results=[]
        )

        response = await client.get(f"{USERS_URL}?email=test")

        assert response.status_code == 200
        call_kwargs = user_management_service.list_users.call_args
        assert call_kwargs.kwargs["email_search"] == "test"


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
            created_at=datetime.now(UTC),
        )

        response = await client.patch(
            f"{USERS_URL}/u-1",
            json={"is_verified": True},
        )

        assert response.status_code == 200
        assert response.json()["is_verified"] is True


class TestResetPasswordViaPatch:
    async def test_admin_can_reset_user_password(
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
            created_at=datetime.now(UTC),
        )

        response = await client.patch(
            f"{USERS_URL}/u-1",
            json={"password": "newsecurepassword"},
        )

        assert response.status_code == 200
        call_args = user_management_service.patch_user.call_args
        assert call_args.args[0] == "u-1"
        assert call_args.args[1].password == "newsecurepassword"

    async def test_password_too_short_returns_400(
        self,
        client: AsyncClient,
    ) -> None:
        response = await client.patch(
            f"{USERS_URL}/u-1",
            json={"password": "short"},
        )

        assert response.status_code == 400


class TestDeactivateViaPatch:
    async def test_admin_can_deactivate_user_via_patch(
        self,
        client: AsyncClient,
        user_management_service: AsyncMock,
    ) -> None:
        user_management_service.patch_user.return_value = UserResponse(
            id="u-1",
            email="a@example.com",
            is_active=False,
            is_superuser=False,
            is_verified=True,
            created_at=datetime.now(UTC),
        )

        response = await client.patch(
            f"{USERS_URL}/u-1",
            json={"is_active": False},
        )

        assert response.status_code == 200
        assert response.json()["is_active"] is False
