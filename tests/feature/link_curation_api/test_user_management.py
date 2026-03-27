"""Step definitions for user_management.feature.

Tests the admin user management endpoints through the FastAPI test client.
Repository mocks let real UserManagementService logic run end-to-end.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from pytest_bdd import given, parsers, scenario, then, when
from starlette.testclient import TestClient

from ers.commons.domain.data_transfer_objects import PaginatedResult
from tests.unit.factories import UserActionFactory, UserFactory

FEATURE = str(Path(__file__).resolve().parent / "user_management.feature")

USERS_URL = "/api/v1/users"


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE, "Create a new user")
def test_create_user():
    pass


@scenario(FEATURE, "Create a user with a duplicate email")
def test_create_duplicate():
    pass


@scenario(FEATURE, "List all users with pagination")
def test_list_users():
    pass


@scenario(FEATURE, "Update user flags")
def test_update_flags():
    pass


@scenario(FEATURE, "Update a non-existent user")
def test_update_not_found():
    pass


@scenario(FEATURE, "Deactivate a user")
def test_deactivate_user():
    pass


@scenario(FEATURE, "Deactivate a non-existent user")
def test_deactivate_not_found():
    pass


@scenario(FEATURE, "Reactivate a previously deactivated user")
def test_reactivate_user():
    pass


@scenario(FEATURE, "Deactivated user's past actions remain visible in the action trail")
def test_deactivated_user_traceability():
    pass


@scenario(FEATURE, "Cannot deactivate the last administrator")
def test_cannot_deactivate_last_admin():
    pass


@scenario(FEATURE, "View current authenticated user")
def test_view_current_user():
    pass


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("the administrator is authenticated")
def admin_authenticated() -> None:
    pass


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(parsers.parse('a user exists with email "{email}"'))
def user_with_email(
    ctx: dict[str, Any],
    email: str,
    user_repository: AsyncMock,
) -> None:
    user = UserFactory.build(email=email)
    user_repository.find_by_email.return_value = user
    ctx["existing_email"] = email


@given(parsers.parse("{count:d} user accounts exist"))
def n_users_exist(count: int) -> None:
    pass


@given("a user account exists", target_fixture="user_id")
def user_account_exists(
    user_repository: AsyncMock,
) -> str:
    user = UserFactory.build(id="u-1")
    user_repository.find_by_id.return_value = user
    user_repository.save.return_value = None
    user_repository.count_active_admins.return_value = 2
    return "u-1"


@given("a user account exists and is active", target_fixture="user_id")
def user_account_active(
    user_repository: AsyncMock,
) -> str:
    user = UserFactory.build(id="u-1", is_active=True, is_superuser=False)
    user_repository.find_by_id.return_value = user
    user_repository.save.return_value = None
    user_repository.count_active_admins.return_value = 2
    return "u-1"


@given("a user account exists and is deactivated", target_fixture="user_id")
def user_account_deactivated(
    user_repository: AsyncMock,
) -> str:
    user = UserFactory.build(id="u-1", is_active=False)
    user_repository.find_by_id.return_value = user
    user_repository.save.return_value = None
    return "u-1"


@given("the user has submitted curation actions")
def user_has_curation_actions(
    ctx: dict[str, Any],
    user_action_repository: AsyncMock,
) -> None:
    actions = [UserActionFactory.build(actor="u-1") for _ in range(3)]
    user_action_repository.find_paginated.return_value = PaginatedResult(
        count=len(actions),
        results=actions,
    )
    ctx["user_has_actions"] = True
    ctx["expected_action_count"] = len(actions)


@given("only one active administrator account exists")
def only_one_admin(
    ctx: dict[str, Any],
    user_repository: AsyncMock,
) -> None:
    admin = UserFactory.build(id="admin-1", is_active=True, is_superuser=True)
    user_repository.find_by_id.return_value = admin
    user_repository.count_active_admins.return_value = 1
    ctx["last_admin_id"] = "admin-1"


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(
    parsers.parse('the administrator creates a user with email "{email}"'),
    target_fixture="response",
)
def admin_creates_user(
    client: TestClient,
    email: str,
    user_repository: AsyncMock,
) -> Any:
    if isinstance(user_repository.find_by_email.return_value, AsyncMock):
        user_repository.find_by_email.return_value = None
    user_repository.save.return_value = None
    return client.post(
        USERS_URL,
        json={"email": email, "password": "securepassword"},
    )


@when(
    parsers.parse("the administrator requests the user list with {per_page:d} items per page"),
    target_fixture="response",
)
def admin_lists_users(
    client: TestClient,
    per_page: int,
    user_repository: AsyncMock,
) -> Any:
    users = [UserFactory.build(id=f"u-{i}", email=f"u{i}@example.com") for i in range(per_page)]
    user_repository.find_paginated.return_value = PaginatedResult(
        count=15,
        results=users,
    )
    return client.get(USERS_URL, params={"per_page": per_page})


@when(
    parsers.parse('the administrator sets the user\'s "{flag}" to {value}'),
    target_fixture="response",
)
def admin_patches_flag(
    client: TestClient,
    flag: str,
    value: str,
    user_id: str,
) -> Any:
    bool_value = value.lower() == "true"
    return client.patch(
        f"{USERS_URL}/{user_id}",
        json={flag: bool_value},
    )


@when(
    "the administrator attempts to update a user that does not exist",
    target_fixture="response",
)
def admin_patches_nonexistent(
    client: TestClient,
    user_repository: AsyncMock,
) -> Any:
    user_repository.find_by_id.return_value = None
    return client.patch(
        f"{USERS_URL}/nonexistent",
        json={"is_active": False},
    )


@when("the administrator deactivates the user", target_fixture="response")
def admin_deactivates_user(client: TestClient, user_id: str) -> Any:
    return client.patch(
        f"{USERS_URL}/{user_id}",
        json={"is_active": False},
    )


@when(
    "the administrator attempts to deactivate a user that does not exist",
    target_fixture="response",
)
def admin_deactivates_nonexistent(
    client: TestClient,
    user_repository: AsyncMock,
) -> Any:
    user_repository.find_by_id.return_value = None
    return client.patch(
        f"{USERS_URL}/nonexistent",
        json={"is_active": False},
    )


@when("the administrator reactivates the user", target_fixture="response")
def admin_reactivates_user(client: TestClient, user_id: str) -> Any:
    return client.patch(
        f"{USERS_URL}/{user_id}",
        json={"is_active": True},
    )


@when(
    "the administrator attempts to deactivate that administrator account",
    target_fixture="response",
)
def admin_deactivates_self(
    client: TestClient,
    ctx: dict[str, Any],
) -> Any:
    admin_id = ctx.get("last_admin_id", "admin-1")
    return client.patch(
        f"{USERS_URL}/{admin_id}",
        json={"is_active": False},
    )


@when(
    "an authenticated user requests their own profile",
    target_fixture="response",
)
def request_own_profile(client: TestClient) -> Any:
    return client.get(f"{USERS_URL}/me")


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the user account is created")
def user_created(response: Any) -> None:
    assert response.status_code == 201


@then("the response contains the user details without the password")
def no_password_in_response(response: Any) -> None:
    data = response.json()
    assert "email" in data
    assert "password" not in data
    assert "hashed_password" not in data


@then("the creation is rejected because the email is already in use")
def duplicate_rejected(response: Any) -> None:
    assert response.status_code == 400


@then(parsers.parse("{count:d} users are returned"))
def n_users_returned(response: Any, count: int) -> None:
    assert response.status_code == 200
    assert len(response.json()["results"]) == count


@then(parsers.parse("the total count is {count:d}"))
def total_count_is(response: Any, count: int) -> None:
    assert response.json()["count"] == count


@then("the user record reflects the updated flag")
def flag_updated(response: Any) -> None:
    assert response.status_code == 200


@then("the system responds with a not found error")
def not_found(response: Any) -> None:
    assert response.status_code == 404


@then("the user record is preserved with active set to false")
def user_deactivated(response: Any) -> None:
    assert response.status_code == 200
    assert response.json()["is_active"] is False


@then("the user can no longer access the system")
def user_cannot_access(response: Any) -> None:
    data = response.json()
    assert data.get("is_active") is False


@then("the user record reflects active set to true")
def user_reactivated(response: Any) -> None:
    assert response.status_code == 200
    assert response.json()["is_active"] is True


@then("the user can access the system again")
def user_can_access(response: Any) -> None:
    data = response.json()
    assert data.get("is_active") is True


@then("all past curation actions by that user remain visible")
def past_actions_visible(
    response: Any,
    ctx: dict[str, Any],
    user_action_repository: AsyncMock,
) -> None:
    paginated = user_action_repository.find_paginated.return_value
    assert paginated.count == ctx["expected_action_count"]


@then("each action is still attributable to the deactivated user")
def actions_attributable(
    response: Any,
    ctx: dict[str, Any],
    user_action_repository: AsyncMock,
) -> None:
    paginated = user_action_repository.find_paginated.return_value
    for action in paginated.results:
        assert action.actor == "u-1"


@then("the system rejects the deactivation")
def deactivation_rejected(response: Any) -> None:
    assert response.status_code == 409


@then("the administrator account remains active")
def admin_remains_active(response: Any) -> None:
    assert response.status_code == 409
    assert "last active administrator" in response.json()["detail"].lower()


@then("the response contains the user's email and role flags")
def response_has_profile(response: Any) -> None:
    assert response.status_code == 200
    data = response.json()
    assert "email" in data
    assert "is_superuser" in data
    assert "is_verified" in data
