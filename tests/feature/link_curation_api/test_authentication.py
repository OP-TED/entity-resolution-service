"""Step definitions for authentication.feature.

Tests the POST /api/v1/auth/* endpoints (register, login, refresh) through
the FastAPI test client. Repository + adapter mocks let real AuthService logic
run end-to-end.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from pytest_bdd import given, parsers, scenario, then, when
from starlette.testclient import TestClient

from ers.users.domain.exceptions import AuthenticationError
from tests.unit.factories import UserFactory

FEATURE = str(Path(__file__).resolve().parent / "authentication.feature")

AUTH_URL = "/api/v1/auth"


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE, "Register a new user account")
def test_register():
    pass


@scenario(FEATURE, "Register with an already used email")
def test_register_duplicate():
    pass


@scenario(FEATURE, "Register with invalid password")
def test_register_invalid_password():
    pass


@scenario(FEATURE, "Log in with valid credentials")
def test_login():
    pass


@scenario(FEATURE, "Log in with wrong password")
def test_login_wrong_password():
    pass


@scenario(FEATURE, "Log in with non-existent email")
def test_login_nonexistent():
    pass


@scenario(FEATURE, "Log in as an inactive user")
def test_login_inactive():
    pass


@scenario(FEATURE, "Refresh tokens with a valid refresh token")
def test_refresh():
    pass


@scenario(FEATURE, "Refresh with an expired token")
def test_refresh_expired():
    pass


@scenario(FEATURE, "Refresh with an access token instead of a refresh token")
def test_refresh_wrong_type():
    pass


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(parsers.parse('a user account exists with email "{email}"'))
def user_exists(ctx: dict[str, Any], email: str, user_repository: AsyncMock) -> None:
    user = UserFactory.build(email=email, hashed_password="hashed:securepassword")
    user_repository.find_by_email.return_value = user
    ctx["existing_email"] = email


@given("a registered and active user exists")
def registered_active_user(
    ctx: dict[str, Any],
    user_repository: AsyncMock,
    token_service: MagicMock,
) -> None:
    user = UserFactory.build(
        email="active@example.com",
        hashed_password="hashed:securepassword",
        is_active=True,
    )
    user_repository.find_by_email.return_value = user
    token_service.create_access_token.return_value = "access-tok"
    token_service.create_refresh_token.return_value = "refresh-tok"
    ctx["user_email"] = "active@example.com"
    ctx["user_password"] = "securepassword"


@given("a registered user exists who has been deactivated")
def deactivated_user(
    ctx: dict[str, Any],
    user_repository: AsyncMock,
) -> None:
    user = UserFactory.build(
        email="inactive@example.com",
        hashed_password="hashed:securepassword",
        is_active=False,
    )
    user_repository.find_by_email.return_value = user
    ctx["user_email"] = "inactive@example.com"
    ctx["user_password"] = "securepassword"


@given("a user has a valid refresh token")
def valid_refresh_token(
    ctx: dict[str, Any],
    user_repository: AsyncMock,
    token_service: MagicMock,
) -> None:
    user = UserFactory.build(is_active=True)
    token_service.decode_token.return_value = {"type": "refresh", "sub": user.id}
    user_repository.find_by_id.return_value = user
    token_service.create_access_token.return_value = "new-access"
    token_service.create_refresh_token.return_value = "new-refresh"
    ctx["refresh_token"] = "valid-refresh-tok"


@given("a user has an expired refresh token")
def expired_refresh_token(
    ctx: dict[str, Any],
    token_service: MagicMock,
) -> None:
    token_service.decode_token.side_effect = AuthenticationError("Invalid token")
    ctx["refresh_token"] = "expired-refresh-tok"


@given("a user has a valid access token")
def valid_access_token(
    ctx: dict[str, Any],
    token_service: MagicMock,
) -> None:
    token_service.decode_token.return_value = {"type": "access", "sub": "user-id"}
    ctx["access_token"] = "valid-access-tok"


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(
    "a new user registers with a valid email and password",
    target_fixture="response",
)
def register_new_user(
    client: TestClient,
    user_repository: AsyncMock,
) -> Any:
    user_repository.find_by_email.return_value = None
    user_repository.save.return_value = None
    return client.post(
        f"{AUTH_URL}/register",
        json={"email": "new@example.com", "password": "securepassword"},
    )


@when(
    parsers.parse('another user attempts to register with email "{email}"'),
    target_fixture="response",
)
def register_duplicate(client: TestClient, email: str) -> Any:
    return client.post(
        f"{AUTH_URL}/register",
        json={"email": email, "password": "securepassword"},
    )


@when(
    parsers.parse("a user attempts to register with a password of length {length:d}"),
    target_fixture="response",
)
def register_bad_password(client: TestClient, length: int) -> Any:
    password = "a" * length
    return client.post(
        f"{AUTH_URL}/register",
        json={"email": "test@example.com", "password": password},
    )


@when("the user logs in with correct credentials", target_fixture="response")
def login_valid(client: TestClient, ctx: dict[str, Any]) -> Any:
    return client.post(
        f"{AUTH_URL}/login",
        json={"email": ctx["user_email"], "password": ctx["user_password"]},
    )


@when("the user logs in with an incorrect password", target_fixture="response")
def login_wrong_password(
    client: TestClient,
    ctx: dict[str, Any],
) -> Any:
    return client.post(
        f"{AUTH_URL}/login",
        json={"email": ctx["user_email"], "password": "wrongpassword"},
    )


@when(
    "a user logs in with an email that is not registered",
    target_fixture="response",
)
def login_nonexistent(client: TestClient, user_repository: AsyncMock) -> Any:
    user_repository.find_by_email.return_value = None
    return client.post(
        f"{AUTH_URL}/login",
        json={"email": "nobody@example.com", "password": "anypassword"},
    )


@when("the user requests a token refresh", target_fixture="response")
def refresh_tokens(client: TestClient, ctx: dict[str, Any]) -> Any:
    return client.post(
        f"{AUTH_URL}/refresh",
        json={"refresh_token": ctx["refresh_token"]},
    )


@when(
    "the user attempts to refresh using the access token",
    target_fixture="response",
)
def refresh_with_access(client: TestClient, ctx: dict[str, Any]) -> Any:
    return client.post(
        f"{AUTH_URL}/refresh",
        json={"refresh_token": ctx["access_token"]},
    )


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the account is created successfully")
def account_created(response: Any) -> None:
    assert response.status_code == 201


@then("the response contains the user's email and identifier")
def response_has_email_and_id(response: Any) -> None:
    data = response.json()
    assert "email" in data
    assert "id" in data


@then("the registration is rejected without revealing whether the email exists")
def register_rejected_vague(response: Any) -> None:
    assert response.status_code == 401


@then("the registration is rejected as invalid")
def register_rejected_invalid(response: Any) -> None:
    assert response.status_code == 422


@then("the response contains an access token and a refresh token")
def response_has_tokens(response: Any) -> None:
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@then("the login is rejected with an authentication error")
def login_rejected(response: Any) -> None:
    assert response.status_code == 401


@then("a new access token and refresh token are returned")
def new_tokens_returned(response: Any) -> None:
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@then("the refresh is rejected with an authentication error")
def refresh_rejected(response: Any) -> None:
    assert response.status_code == 401
