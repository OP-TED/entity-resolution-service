import uuid
from datetime import datetime, timezone

from ers.application.auth_dtos import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserContext,
    UserResponse,
)
from ers.application.ports.password_hasher import PasswordHasher
from ers.application.ports.token_service import TokenService
from ers.application.ports.user_repository import UserRepository
from ers.domain.exceptions import AuthenticationError
from ers.domain.user import User


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        is_verified=user.is_verified,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


class AuthService:
    """Handles registration, login, and token lifecycle."""

    def __init__(
        self,
        user_repository: UserRepository,
        password_hasher: PasswordHasher,
        token_service: TokenService,
    ) -> None:
        self._user_repo = user_repository
        self._hasher = password_hasher
        self._tokens = token_service

    async def register(self, dto: RegisterRequest) -> UserResponse:
        """Register a new user. Returns vague error on duplicate to prevent enumeration."""
        existing = await self._user_repo.find_by_email(dto.email)
        if existing is not None:
            raise AuthenticationError("Registration failed")

        user = User(
            id=str(uuid.uuid4()),
            email=dto.email,
            hashed_password=self._hasher.hash(dto.password),
            created_at=datetime.now(timezone.utc),
        )
        await self._user_repo.save(user)
        return _to_user_response(user)

    async def login(self, dto: LoginRequest) -> TokenResponse:
        """Authenticate user and return token pair."""
        user = await self._user_repo.find_by_email(dto.email)
        if user is None or not self._hasher.verify(dto.password, user.hashed_password):
            raise AuthenticationError("Invalid credentials")

        if not user.is_active:
            raise AuthenticationError("Invalid credentials")

        return self._issue_tokens(user)

    async def refresh(self, dto: RefreshRequest) -> TokenResponse:
        """Issue a new token pair from a valid refresh token."""
        payload = self._tokens.decode_token(dto.refresh_token)
        if payload.get("type") != "refresh":
            raise AuthenticationError("Invalid token type")

        user = await self._user_repo.find_by_id(payload["sub"])
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid credentials")

        return self._issue_tokens(user)

    async def get_current_user_context(self, token: str) -> UserContext:
        """Decode access token and return user context."""
        payload = self._tokens.decode_token(token)
        if payload.get("type") != "access":
            raise AuthenticationError("Invalid token type")

        user = await self._user_repo.find_by_id(payload["sub"])
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid credentials")

        return UserContext(
            id=user.id,
            email=user.email,
            is_superuser=user.is_superuser,
            is_verified=user.is_verified,
        )

    def _issue_tokens(self, user: User) -> TokenResponse:
        extra = {
            "email": user.email,
            "is_superuser": user.is_superuser,
            "is_verified": user.is_verified,
        }
        return TokenResponse(
            access_token=self._tokens.create_access_token(user.id, extra),
            refresh_token=self._tokens.create_refresh_token(user.id),
        )
