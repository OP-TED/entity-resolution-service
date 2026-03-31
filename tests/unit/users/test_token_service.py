from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest

from ers.users.domain.exceptions import AuthenticationError
from ers.users.services.token_service import JWTTokenService

SECRET = "test-secret-key"
ALGORITHM = "HS256"
ACCESS_MINUTES = 15
REFRESH_MINUTES = 60


@pytest.fixture
def token_service() -> JWTTokenService:
    return JWTTokenService(SECRET, ALGORITHM, ACCESS_MINUTES, REFRESH_MINUTES)


class TestCreateAccessToken:
    def test_returns_decodable_jwt(self, token_service: JWTTokenService) -> None:
        token = token_service.create_access_token("user-1", {"role": "admin"})
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])

        assert payload["sub"] == "user-1"
        assert payload["type"] == "access"
        assert payload["role"] == "admin"

    def test_expiry_matches_configured_minutes(self, token_service: JWTTokenService) -> None:
        token = token_service.create_access_token("user-1", {})
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])

        iat = datetime.fromtimestamp(payload["iat"], tz=UTC)
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        assert exp - iat == timedelta(minutes=ACCESS_MINUTES)


class TestCreateRefreshToken:
    def test_returns_decodable_jwt(self, token_service: JWTTokenService) -> None:
        token = token_service.create_refresh_token("user-2")
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])

        assert payload["sub"] == "user-2"
        assert payload["type"] == "refresh"

    def test_expiry_matches_configured_minutes(self, token_service: JWTTokenService) -> None:
        token = token_service.create_refresh_token("user-2")
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])

        iat = datetime.fromtimestamp(payload["iat"], tz=UTC)
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        assert exp - iat == timedelta(minutes=REFRESH_MINUTES)


class TestDecodeToken:
    def test_valid_token_returns_payload(self, token_service: JWTTokenService) -> None:
        token = token_service.create_access_token("user-3", {"foo": "bar"})
        payload = token_service.decode_token(token)

        assert payload["sub"] == "user-3"
        assert payload["foo"] == "bar"

    def test_expired_token_raises_authentication_error(
        self, token_service: JWTTokenService
    ) -> None:
        past = datetime(2020, 1, 1, tzinfo=UTC)
        with patch("ers.users.services.token_service.datetime") as mock_dt:
            mock_dt.now.return_value = past
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            token = token_service.create_access_token("user-4", {})

        with pytest.raises(AuthenticationError, match="expired"):
            token_service.decode_token(token)

    def test_invalid_token_raises_authentication_error(
        self, token_service: JWTTokenService
    ) -> None:
        with pytest.raises(AuthenticationError, match="Invalid token"):
            token_service.decode_token("not-a-valid-token")

    def test_wrong_secret_raises_authentication_error(self, token_service: JWTTokenService) -> None:
        token = jwt.encode(
            {"sub": "user-5", "exp": datetime.now(UTC) + timedelta(hours=1)},
            "different-secret",
            algorithm=ALGORITHM,
        )

        with pytest.raises(AuthenticationError, match="Invalid token"):
            token_service.decode_token(token)
