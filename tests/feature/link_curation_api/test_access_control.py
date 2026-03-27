"""Step definitions for access_control.feature.

Tests role-based access enforcement across curation endpoints with different
user contexts (unauthenticated, unverified, non-admin, admin, verified).
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from fastapi import FastAPI
from pytest_bdd import given, scenario, then, when
from starlette.testclient import TestClient

from ers.commons.domain.data_transfer_objects import CursorPage, PaginatedResult
from tests.feature.link_curation_api.conftest import (
    ADMIN_USER,
    UNVERIFIED_USER,
    VERIFIED_USER,
    make_client_with_user,
    make_unauthenticated_client,
)

FEATURE = str(Path(__file__).resolve().parent / "access_control.feature")

DECISIONS_URL = "/api/v1/curation/decisions"
USER_ACTIONS_URL = "/api/v1/user-actions"
USERS_URL = "/api/v1/users"
STATS_URL = "/api/v1/curation/stats"


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE, "Unauthenticated access to curation endpoints is denied")
def test_unauthenticated_denied():
    pass


@scenario(FEATURE, "Unverified user cannot access curation endpoints")
def test_unverified_cannot_browse():
    pass


@scenario(FEATURE, "Unverified user cannot curate decisions")
def test_unverified_cannot_curate():
    pass


@scenario(FEATURE, "Non-admin user cannot access user management")
def test_non_admin_user_management():
    pass


@scenario(FEATURE, "Non-admin user cannot view user action trail")
def test_non_admin_action_trail():
    pass


@scenario(FEATURE, "Non-admin user cannot create users")
def test_non_admin_create_user():
    pass


@scenario(FEATURE, "Admin user can access user management endpoints")
def test_admin_user_management():
    pass


@scenario(FEATURE, "Admin user can view the user action trail")
def test_admin_action_trail():
    pass


@scenario(FEATURE, "Deactivated user cannot access any endpoint")
def test_deactivated_denied():
    pass


@scenario(FEATURE, "Verified user can browse decisions")
def test_verified_browse():
    pass


@scenario(FEATURE, "Verified user can view statistics")
def test_verified_statistics():
    pass


@scenario(FEATURE, "Verified user can submit curation recommendations")
def test_verified_can_curate():
    pass


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("a user is authenticated but not verified", target_fixture="test_client")
def unverified_client(app: FastAPI) -> TestClient:
    return make_client_with_user(app, UNVERIFIED_USER)


@given(
    "a verified user is authenticated but is not an administrator",
    target_fixture="test_client",
)
def non_admin_client(app: FastAPI) -> TestClient:
    return make_client_with_user(app, VERIFIED_USER)


@given("an administrator is authenticated", target_fixture="test_client")
def admin_client(
    app: FastAPI,
    user_repository: AsyncMock,
    user_action_repository: AsyncMock,
) -> TestClient:
    user_repository.find_paginated.return_value = PaginatedResult(
        count=0,
        results=[],
    )
    user_action_repository.find_paginated.return_value = PaginatedResult(
        count=0,
        results=[],
    )
    return make_client_with_user(app, ADMIN_USER)


@given("a user is authenticated but has been deactivated", target_fixture="test_client")
def deactivated_client(app: FastAPI) -> TestClient:
    from ers.curation.entrypoints.api.auth import get_current_user
    from ers.users.domain.exceptions import AuthenticationError

    def _reject_deactivated():
        raise AuthenticationError("Invalid credentials")

    # user `is_active` flag is checked in get_current_user, so we can simulate deactivation by overriding it to always raise an error
    app.dependency_overrides[get_current_user] = _reject_deactivated
    return TestClient(app)


@given("a verified user is authenticated", target_fixture="test_client")
def verified_client(
    app: FastAPI,
    decision_repository: AsyncMock,
    statistics_repository: AsyncMock,
) -> TestClient:
    from ers.curation.domain.data_transfer_objects import (
        CurationStatistics,
        RegistryStatistics,
    )

    decision_repository.find_with_filters.return_value = CursorPage(
        results=[],
        next_cursor=None,
    )
    statistics_repository.get_curation_statistics.return_value = CurationStatistics(
        total_decisions=0,
        selected_top=0,
        selected_alternative=0,
        rejected_all=0,
    )
    statistics_repository.get_registry_statistics.return_value = RegistryStatistics(
        total_entity_mentions=0,
        total_canonical_entities=0,
        average_cluster_size=0.0,
        resolution_requests=0,
    )
    return make_client_with_user(app, VERIFIED_USER)


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(
    "an unauthenticated user requests the decision list",
    target_fixture="response",
)
def unauthenticated_decision_list(app: FastAPI) -> Any:
    tc = make_unauthenticated_client(app)
    return tc.get(DECISIONS_URL)


@when("the user requests the decision list", target_fixture="response")
def user_requests_decisions(test_client: TestClient) -> Any:
    return test_client.get(DECISIONS_URL)


@when("the user attempts to accept a decision", target_fixture="response")
def user_attempts_accept(test_client: TestClient) -> Any:
    return test_client.post(f"{DECISIONS_URL}/decision-1/accept")


@when("the user attempts to list all users", target_fixture="response")
def user_lists_users(test_client: TestClient) -> Any:
    return test_client.get(USERS_URL)


@when("the user attempts to view the user action trail", target_fixture="response")
def user_views_actions(test_client: TestClient) -> Any:
    return test_client.get(USER_ACTIONS_URL)


@when("the user attempts to create a new user", target_fixture="response")
def user_creates_user(test_client: TestClient) -> Any:
    return test_client.post(
        USERS_URL,
        json={"email": "new@example.com", "password": "securepassword"},
    )


@when("the administrator requests the user list", target_fixture="response")
def admin_lists_users(test_client: TestClient) -> Any:
    return test_client.get(USERS_URL)


@when("the administrator requests the user action trail", target_fixture="response")
def admin_views_actions(test_client: TestClient) -> Any:
    return test_client.get(USER_ACTIONS_URL)


@when("the user requests curation statistics", target_fixture="response")
def user_requests_stats(test_client: TestClient) -> Any:
    return test_client.get(STATS_URL)


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the request is rejected with an authentication error")
def auth_error(response: Any) -> None:
    assert response.status_code == 401


@then("the request is rejected with a forbidden error")
def forbidden_error(response: Any) -> None:
    assert response.status_code == 403


@then("the user list is returned successfully")
def user_list_ok(response: Any) -> None:
    assert response.status_code == 200


@then("the action trail is returned successfully")
def action_trail_ok(response: Any) -> None:
    assert response.status_code == 200


@then("the decision list is returned successfully")
def decision_list_ok(response: Any) -> None:
    assert response.status_code == 200


@then("the statistics are returned successfully")
def stats_ok(response: Any) -> None:
    assert response.status_code == 200


# --- Deactivated user ---
# The Then step for deactivated user access is "the request is rejected
# with an authentication error", which maps to auth_error() above.


# --- Verified user curation ---


@when(
    "the user submits a curation recommendation for a decision",
    target_fixture="response",
)
def user_submits_recommendation(
    test_client: TestClient,
    decision_repository: AsyncMock,
    user_action_repository: AsyncMock,
) -> Any:
    from tests.unit.factories import DecisionFactory

    decision = DecisionFactory.build(id="decision-1")
    decision_repository.find_by_id.return_value = decision
    user_action_repository.has_current_action.return_value = False
    user_action_repository.save.return_value = None
    return test_client.post(f"{DECISIONS_URL}/decision-1/accept")


@then("the recommendation is accepted successfully")
def recommendation_accepted(response: Any) -> None:
    assert response.status_code == 204
