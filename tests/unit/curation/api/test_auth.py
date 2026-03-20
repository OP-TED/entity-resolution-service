from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fastapi import FastAPI
from httpx import AsyncClient

from ers.curation.entrypoints.api.auth import get_current_user
from ers.users.domain.data_transfer_objects import (
    TokenResponse,
    UserContext,
    UserResponse,
)
from ers.users.domain.exceptions import AuthenticationError

AUTH_URL = "/api/v1/auth"


class TestRegisterEndpoint:
    async def test_register_returns_201(
        self,
        client: AsyncClient,
        auth_service: AsyncMock,
    ) -> None:
        auth_service.register.return_value = UserResponse(
            id="u-1",
            email="new@example.com",
            is_active=True,
            is_superuser=False,
            is_verified=False,
            created_at=datetime.now(UTC),
        )

        response = await client.post(
            f"{AUTH_URL}/register",
            json={"email": "new@example.com", "password": "securepassword"},
        )

        assert response.status_code == 201
        assert response.json()["email"] == "new@example.com"

    async def test_register_duplicate_returns_401(
        self,
        client: AsyncClient,
        auth_service: AsyncMock,
    ) -> None:
        auth_service.register.side_effect = AuthenticationError("Registration failed")

        response = await client.post(
            f"{AUTH_URL}/register",
            json={"email": "dup@example.com", "password": "securepassword"},
        )

        assert response.status_code == 401

    async def test_register_short_password_returns_422(
        self,
        client: AsyncClient,
    ) -> None:
        response = await client.post(
            f"{AUTH_URL}/register",
            json={"email": "x@example.com", "password": "short"},
        )

        assert response.status_code == 422

    async def test_register_invalid_email_returns_422(
        self,
        client: AsyncClient,
    ) -> None:
        response = await client.post(
            f"{AUTH_URL}/register",
            json={"email": "not-an-email", "password": "securepassword"},
        )

        assert response.status_code == 422


class TestLoginEndpoint:
    async def test_login_returns_tokens(
        self,
        client: AsyncClient,
        auth_service: AsyncMock,
    ) -> None:
        auth_service.login.return_value = TokenResponse(access_token="at", refresh_token="rt")

        response = await client.post(
            f"{AUTH_URL}/login",
            json={"email": "user@example.com", "password": "pw"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "at"
        assert data["token_type"] == "bearer"

    async def test_login_invalid_credentials_returns_401(
        self,
        client: AsyncClient,
        auth_service: AsyncMock,
    ) -> None:
        auth_service.login.side_effect = AuthenticationError("Invalid credentials")

        response = await client.post(
            f"{AUTH_URL}/login",
            json={"email": "user@example.com", "password": "wrong"},
        )

        assert response.status_code == 401


class TestRefreshEndpoint:
    async def test_refresh_returns_new_tokens(
        self,
        client: AsyncClient,
        auth_service: AsyncMock,
    ) -> None:
        auth_service.refresh.return_value = TokenResponse(
            access_token="new-at", refresh_token="new-rt"
        )

        response = await client.post(
            f"{AUTH_URL}/refresh",
            json={"refresh_token": "old-rt"},
        )

        assert response.status_code == 200
        assert response.json()["access_token"] == "new-at"


class TestProtectedEndpointWithoutAuth:
    async def test_protected_endpoint_returns_401_without_token(
        self,
        app: FastAPI,
    ) -> None:
        # Remove the get_current_user override so auth is actually enforced
        app.dependency_overrides.pop(get_current_user, None)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as unauthed:
            response = await unauthed.get("/api/v1/curation/decisions")

        assert response.status_code == 401


class TestProtectedEndpointUnverified:
    async def test_unverified_user_gets_403_on_protected_route(
        self,
        app: FastAPI,
    ) -> None:
        unverified = UserContext(
            id="u-1",
            email="unverified@example.com",
            is_active=True,
            is_superuser=False,
            is_verified=False,
        )
        app.dependency_overrides[get_current_user] = lambda: unverified

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.get("/api/v1/curation/decisions")

        assert response.status_code == 403
