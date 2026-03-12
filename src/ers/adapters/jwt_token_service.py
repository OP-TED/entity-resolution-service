from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from ers.application.ports.token_service import TokenService
from ers.domain.exceptions import AuthenticationError


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
        now = datetime.now(timezone.utc)
        payload = {
            "sub": subject,
            "type": "access",
            "iat": now,
            "exp": now + _minutes(self._access_expire),
            **extra_claims,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def create_refresh_token(self, subject: str) -> str:
        now = datetime.now(timezone.utc)
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
