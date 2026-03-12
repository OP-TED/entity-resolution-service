from unittest.mock import AsyncMock, create_autospec

import pytest

from ers.application.auth_dtos import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    UserContext,
)
from ers.application.ports.password_hasher import PasswordHasher
from ers.application.ports.token_service import TokenService
from ers.application.ports.user_repository import UserRepository
from ers.application.services.auth_service import AuthService
from ers.domain.exceptions import AuthenticationError
from tests.factories import UserFactory


@pytest.fixture
def user_repository() -> AsyncMock:
    return create_autospec(UserRepository, instance=True)


@pytest.fixture
def password_hasher() -> AsyncMock:
    return create_autospec(PasswordHasher, instance=True)


@pytest.fixture
def token_service() -> AsyncMock:
    return create_autospec(TokenService, instance=True)


@pytest.fixture
def auth_service(
    user_repository: AsyncMock,
    password_hasher: AsyncMock,
    token_service: AsyncMock,
) -> AuthService:
    return AuthService(
        user_repository=user_repository,
        password_hasher=password_hasher,
        token_service=token_service,
    )


class TestRegister:
    async def test_register_creates_user(
        self,
        auth_service: AuthService,
        user_repository: AsyncMock,
        password_hasher: AsyncMock,
    ) -> None:
        user_repository.find_by_email.return_value = None
        password_hasher.hash.return_value = "hashed-pw"
        user_repository.save.side_effect = lambda u: u

        result = await auth_service.register(
            RegisterRequest(email="new@example.com", password="securepassword")
        )

        assert result.email == "new@example.com"
        user_repository.save.assert_called_once()
        saved_user = user_repository.save.call_args[0][0]
        assert saved_user.hashed_password == "hashed-pw"

    async def test_register_duplicate_email_raises_vague_error(
        self,
        auth_service: AuthService,
        user_repository: AsyncMock,
    ) -> None:
        user_repository.find_by_email.return_value = UserFactory.build()

        with pytest.raises(AuthenticationError, match="Registration failed"):
            await auth_service.register(
                RegisterRequest(email="existing@example.com", password="securepassword")
            )


class TestLogin:
    async def test_login_valid_credentials_returns_tokens(
        self,
        auth_service: AuthService,
        user_repository: AsyncMock,
        password_hasher: AsyncMock,
        token_service: AsyncMock,
    ) -> None:
        user = UserFactory.build(is_active=True)
        user_repository.find_by_email.return_value = user
        password_hasher.verify.return_value = True
        token_service.create_access_token.return_value = "access-tok"
        token_service.create_refresh_token.return_value = "refresh-tok"

        result = await auth_service.login(LoginRequest(email=user.email, password="pw"))

        assert result.access_token == "access-tok"
        assert result.refresh_token == "refresh-tok"
        assert result.token_type == "bearer"

    async def test_login_invalid_password_raises(
        self,
        auth_service: AuthService,
        user_repository: AsyncMock,
        password_hasher: AsyncMock,
    ) -> None:
        user = UserFactory.build(is_active=True)
        user_repository.find_by_email.return_value = user
        password_hasher.verify.return_value = False

        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            await auth_service.login(LoginRequest(email=user.email, password="wrong"))

    async def test_login_unknown_email_raises(
        self,
        auth_service: AuthService,
        user_repository: AsyncMock,
    ) -> None:
        user_repository.find_by_email.return_value = None

        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            await auth_service.login(
                LoginRequest(email="nobody@example.com", password="pw")
            )

    async def test_login_inactive_user_raises(
        self,
        auth_service: AuthService,
        user_repository: AsyncMock,
        password_hasher: AsyncMock,
    ) -> None:
        user = UserFactory.build(is_active=False)
        user_repository.find_by_email.return_value = user
        password_hasher.verify.return_value = True

        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            await auth_service.login(LoginRequest(email=user.email, password="pw"))


class TestRefresh:
    async def test_refresh_valid_token_returns_new_tokens(
        self,
        auth_service: AuthService,
        token_service: AsyncMock,
        user_repository: AsyncMock,
    ) -> None:
        user = UserFactory.build(is_active=True)
        token_service.decode_token.return_value = {
            "sub": user.id,
            "type": "refresh",
        }
        user_repository.find_by_id.return_value = user
        token_service.create_access_token.return_value = "new-access"
        token_service.create_refresh_token.return_value = "new-refresh"

        result = await auth_service.refresh(RefreshRequest(refresh_token="old-refresh"))

        assert result.access_token == "new-access"
        assert result.refresh_token == "new-refresh"

    async def test_refresh_wrong_token_type_raises(
        self,
        auth_service: AuthService,
        token_service: AsyncMock,
    ) -> None:
        token_service.decode_token.return_value = {
            "sub": "user-1",
            "type": "access",
        }

        with pytest.raises(AuthenticationError, match="Invalid token type"):
            await auth_service.refresh(RefreshRequest(refresh_token="an-access-token"))

    async def test_refresh_inactive_user_raises(
        self,
        auth_service: AuthService,
        token_service: AsyncMock,
        user_repository: AsyncMock,
    ) -> None:
        user = UserFactory.build(is_active=False)
        token_service.decode_token.return_value = {
            "sub": user.id,
            "type": "refresh",
        }
        user_repository.find_by_id.return_value = user

        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            await auth_service.refresh(RefreshRequest(refresh_token="refresh-tok"))


class TestGetCurrentUserContext:
    async def test_returns_user_context(
        self,
        auth_service: AuthService,
        token_service: AsyncMock,
        user_repository: AsyncMock,
    ) -> None:
        user = UserFactory.build(is_active=True, is_superuser=True, is_verified=True)
        token_service.decode_token.return_value = {
            "sub": user.id,
            "type": "access",
        }
        user_repository.find_by_id.return_value = user

        ctx = await auth_service.get_current_user_context("access-tok")

        assert isinstance(ctx, UserContext)
        assert ctx.id == user.id
        assert ctx.email == user.email
        assert ctx.is_superuser is True

    async def test_wrong_token_type_raises(
        self,
        auth_service: AuthService,
        token_service: AsyncMock,
    ) -> None:
        token_service.decode_token.return_value = {
            "sub": "user-1",
            "type": "refresh",
        }

        with pytest.raises(AuthenticationError, match="Invalid token type"):
            await auth_service.get_current_user_context("refresh-tok")

    async def test_inactive_user_raises(
        self,
        auth_service: AuthService,
        token_service: AsyncMock,
        user_repository: AsyncMock,
    ) -> None:
        user = UserFactory.build(is_active=False)
        token_service.decode_token.return_value = {
            "sub": user.id,
            "type": "access",
        }
        user_repository.find_by_id.return_value = user

        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            await auth_service.get_current_user_context("access-tok")
