from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from ers.users.domain.exceptions import AuthenticationError


class TokenService(ABC):
    """Port for JWT token operations."""

    @abstractmethod
    def create_access_token(self, subject: str, extra_claims: dict[str, Any]) -> str:
        """Create a short-lived access token."""

    @abstractmethod
    def create_refresh_token(self, subject: str) -> str:
        """Create a longer-lived refresh token."""

    @abstractmethod
    def decode_token(self, token: str) -> dict[str, Any]:
        """Decode and validate a token. Raises AuthenticationError on failure."""


class JWTTokenService(TokenService):
    """PyJWT-based token service."""

    def __init__(
        self,
        secret_key: str,
        algorithm: str,
        access_expire_minutes: int,
        refresh_expire_minutes: int,
    ) -> None:
        self._secret = secret_key
        self._algorithm = algorithm
        self._access_expire = access_expire_minutes
        self._refresh_expire = refresh_expire_minutes

    def create_access_token(self, subject: str, extra_claims: dict[str, Any]) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": subject,
            "type": "access",
            "iat": now,
            "exp": now + _minutes(self._access_expire),
            **extra_claims,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def create_refresh_token(self, subject: str) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": subject,
            "type": "refresh",
            "iat": now,
            "exp": now + _minutes(self._refresh_expire),
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def decode_token(self, token: str) -> dict[str, Any]:
        try:
            return jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Token has expired")
        except jwt.InvalidTokenError:
            raise AuthenticationError("Invalid token")


def _minutes(n: int) -> timedelta:
    return timedelta(minutes=n)
