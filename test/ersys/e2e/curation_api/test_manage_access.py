"""Step definitions for tests/e2e/curation_api/manage_access.feature.

UC-W5 — Manage Curator Access.

Implements:
  - Grant curator access (scenario 1)
  - Suspend curator access (scenario 2)
  - Reactivate suspended access (scenario 3)
  - Retire access permanently (scenario 4)
  - Access management failure leaves no partial state (scenario 5)
"""
import httpx
import pytest
from pytest_bdd import given, scenario, then, when

from test.ersys.e2e.curation_api.conftest import TEST_CURATOR_EMAIL, TEST_CURATOR_PASSWORD

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

@scenario(
    "manage_access.feature",
    "Admin grants curator access to a new user — user can subsequently perform curation actions",
)
def test_grant_curator_access():
    pass


@scenario(
    "manage_access.feature",
    "Admin suspends an active curator — subsequent curation actions are rejected",
)
def test_suspend_curator_access():
    pass


@scenario(
    "manage_access.feature",
    "Admin reactivates a previously suspended curator — curation actions succeed again",
)
def test_reactivate_curator_access():
    pass


@scenario(
    "manage_access.feature",
    "Admin retires a curator permanently — user cannot act but past records are preserved",
)
def test_retire_curator_access():
    pass


@scenario(
    "manage_access.feature",
    "Access management operation that fails leaves no partial or ambiguous access state",
)
def test_access_management_failure():
    pass


# ---------------------------------------------------------------------------
# Shared context fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    """Mutable dict for intra-scenario shared state."""
    return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login_as_curator(curation_api_url: str) -> str | None:
    """Attempt to log in as the test curator.  Returns access_token or None on failure."""
    resp = httpx.post(
        f"{curation_api_url}/api/v1/auth/login",
        json={"email": TEST_CURATOR_EMAIL, "password": TEST_CURATOR_PASSWORD},
        timeout=10.0,
    )
    if resp.status_code == 200:
        data = resp.json()
        return data.get("access_token") or data.get("token")
    return None


def _curator_client(curation_api_url: str, token: str) -> httpx.Client:
    """Build an httpx.Client authenticated as the test curator."""
    return httpx.Client(
        base_url=curation_api_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )


def _attempt_curation(curation_api_url: str, token: str, decision_id: str, cluster_id: str) -> httpx.Response:
    """Submit a /assign call using a freshly-built curator client."""
    with _curator_client(curation_api_url, token) as client:
        return client.post(
            f"/api/v1/curation/decisions/{decision_id}/assign",
            json={"cluster_id": cluster_id},
        )


# Background steps "the access registry contains no test curator accounts",
# "the user action log is empty" are bound globally in tests/e2e/conftest.py.

# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------

@given("an identified user does not yet exist in the access registry", target_fixture="curator_state")
def given_user_not_in_registry():
    """No action needed — the test account should not exist due to background cleanup."""
    return {"user_id": None, "status": "not_created"}


@given("an identified user has active curator access in the access registry", target_fixture="curator_state")
def given_user_has_active_access(curation_client, new_curator_payload):
    """Create the test curator via the admin API and confirm they are active."""
    resp = curation_client.post("/api/v1/users", json=new_curator_payload)
    assert resp.status_code == 201, (
        f"Expected 201 when granting access, got {resp.status_code}. "
        f"Body: {resp.json()}"
    )
    body = resp.json()
    user_id = body.get("id")
    assert user_id is not None, f"Expected 'id' in user creation response. Body: {body}"
    return {"user_id": user_id, "status": "active"}


@given("an identified user has suspended curator access in the access registry", target_fixture="curator_state")
def given_user_has_suspended_access(curation_client, new_curator_payload):
    """Create the test curator and then immediately suspend them."""
    resp = curation_client.post("/api/v1/users", json=new_curator_payload)
    assert resp.status_code == 201, (
        f"Expected 201 when creating user for suspension setup, got {resp.status_code}. "
        f"Body: {resp.json()}"
    )
    body = resp.json()
    user_id = body.get("id")
    assert user_id is not None

    suspend_resp = curation_client.patch(
        f"/api/v1/users/{user_id}",
        json={"is_active": False},
    )
    assert suspend_resp.status_code == 200, (
        f"Expected 200 when suspending curator in setup, got {suspend_resp.status_code}. "
        f"Body: {suspend_resp.json()}"
    )
    return {"user_id": user_id, "status": "suspended"}


@given("that user has previously submitted re-evaluation requests recorded in the user action log")
def given_user_has_prior_actions(curator_state, decision_in_store, curation_api_url):
    """Log in as the curator and submit one /assign to produce a user_actions record.

    We must call the curation endpoint as the curator (not as admin) so the record
    is attributed to the curator account.
    """
    token = _login_as_curator(curation_api_url)
    assert token is not None, (
        "Could not log in as test curator to pre-seed user action log. "
        "Check that the account was created and is active."
    )
    decision_id = decision_in_store["decision_id"]
    cluster_id = decision_in_store["cluster_id"]
    resp = _attempt_curation(curation_api_url, token, decision_id, cluster_id)
    assert resp.status_code == 204, (
        f"Expected 204 when pre-seeding curator action, got {resp.status_code}. "
        f"Body: {resp.json() if resp.content else 'empty'}"
    )


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------

@when("an Admin grants curator access to that user")
def when_admin_grants_access(ctx, curation_client, new_curator_payload):
    resp = curation_client.post("/api/v1/users", json=new_curator_payload)
    ctx["response"] = resp
    ctx["response_body"] = resp.json() if resp.content else {}


@when("an Admin suspends curator access for that user")
def when_admin_suspends_access(ctx, curation_client, curator_state):
    user_id = curator_state["user_id"]
    resp = curation_client.patch(
        f"/api/v1/users/{user_id}",
        json={"is_active": False},
    )
    ctx["response"] = resp
    ctx["response_body"] = resp.json() if resp.content else {}
    ctx["user_id"] = user_id


@when("an Admin reactivates curator access for that user")
def when_admin_reactivates_access(ctx, curation_client, curator_state):
    user_id = curator_state["user_id"]
    resp = curation_client.patch(
        f"/api/v1/users/{user_id}",
        json={"is_active": True},
    )
    ctx["response"] = resp
    ctx["response_body"] = resp.json() if resp.content else {}
    ctx["user_id"] = user_id


@when("an Admin retires curator access for that user permanently")
def when_admin_retires_access(ctx, curation_client, curator_state):
    user_id = curator_state["user_id"]
    resp = curation_client.patch(
        f"/api/v1/users/{user_id}",
        json={"is_active": False, "is_verified": False},
    )
    ctx["response"] = resp
    ctx["response_body"] = resp.json() if resp.content else {}
    ctx["user_id"] = user_id


@when("an Admin attempts an access modification that the system cannot process")
def when_admin_attempts_invalid_modification(ctx, curation_client, curator_state):
    """Attempt a PATCH with an invalid payload (e.g., unknown fields or constraint violation).

    We send a deliberately malformed body to trigger a 400/422 from the API.
    """
    user_id = curator_state["user_id"]
    resp = curation_client.patch(
        f"/api/v1/users/{user_id}",
        json={"is_active": "not-a-boolean"},  # invalid type
    )
    ctx["response"] = resp
    ctx["response_body"] = resp.json() if resp.content else {}
    ctx["user_id"] = user_id
    ctx["original_user_id"] = user_id


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------

@then("the access grant operation is accepted")
def then_grant_accepted(ctx):
    status = ctx["response"].status_code
    assert status == 201, (
        f"Expected HTTP 201 for access grant operation, got {status}. "
        f"Body: {ctx.get('response_body')}"
    )
    body = ctx["response_body"]
    user_id = body.get("id")
    assert user_id is not None, f"Expected 'id' in response body. Body: {body}"
    ctx["user_id"] = user_id


@then("the user is present in the access registry with an active curator role")
def then_user_present_and_active(ctx, curation_api_url):
    # Verify by attempting login — only an active, verified account can authenticate.
    token = _login_as_curator(curation_api_url)
    assert token is not None, (
        "Expected newly-created curator to be able to log in (is_active=True, is_verified=True), "
        "but login returned no token."
    )


@then("that user can successfully submit a re-evaluation request using their credentials")
def then_curator_can_perform_curation(ctx, decision_in_store, curation_api_url):
    token = _login_as_curator(curation_api_url)
    assert token is not None, (
        "Could not log in as the newly-created test curator. "
        "Check that is_active and is_verified are True."
    )
    decision_id = decision_in_store["decision_id"]
    cluster_id = decision_in_store["cluster_id"]
    resp = _attempt_curation(curation_api_url, token, decision_id, cluster_id)
    assert resp.status_code == 204, (
        f"Expected HTTP 204 for curation action by new curator, got {resp.status_code}. "
        f"Body: {resp.json() if resp.content else 'empty'}"
    )


@then("the suspension operation is accepted")
def then_suspension_accepted(ctx):
    status = ctx["response"].status_code
    assert status == 200, (
        f"Expected HTTP 200 for suspension operation, got {status}. "
        f"Body: {ctx.get('response_body')}"
    )


@then("the user's status in the access registry reflects the suspended state")
def then_user_is_suspended(ctx):
    # Verify from the PATCH response — it returns the updated UserResponse.
    body = ctx["response_body"]
    assert body.get("is_active") is False, (
        f"Expected is_active=False in PATCH response for suspended curator. Body: {body}"
    )


@then("a subsequent re-evaluation request submitted by that user is rejected with an authorisation failure")
def then_suspended_curator_cannot_curate(ctx, decision_in_store, curation_api_url):
    """The suspended user cannot obtain a valid token or their token is rejected."""
    token = _login_as_curator(curation_api_url)
    if token is None:
        # Login failed — inactive accounts cannot authenticate. This is the expected outcome.
        return
    # If the API issues a token even for inactive accounts, the curation call
    # should still be rejected with 401 or 403.
    decision_id = decision_in_store["decision_id"]
    cluster_id = decision_in_store["cluster_id"]
    resp = _attempt_curation(curation_api_url, token, decision_id, cluster_id)
    assert resp.status_code in (401, 403), (
        f"Expected 401 or 403 for suspended curator attempting curation, "
        f"got {resp.status_code}. Body: {resp.json() if resp.content else 'empty'}"
    )


@then("the reactivation operation is accepted")
def then_reactivation_accepted(ctx):
    status = ctx["response"].status_code
    assert status == 200, (
        f"Expected HTTP 200 for reactivation operation, got {status}. "
        f"Body: {ctx.get('response_body')}"
    )


@then("the user's status in the access registry reflects the active state")
def then_user_is_active(ctx):
    # Verify from the PATCH response — it returns the updated UserResponse.
    body = ctx["response_body"]
    assert body.get("is_active") is True, (
        f"Expected is_active=True in PATCH response for reactivated curator. Body: {body}"
    )


@then("a subsequent re-evaluation request submitted by that user is accepted")
def then_reactivated_curator_can_curate(ctx, decision_in_store, curation_api_url):
    token = _login_as_curator(curation_api_url)
    assert token is not None, (
        "Could not log in as reactivated test curator. "
        "Check that is_active=True after reactivation."
    )
    decision_id = decision_in_store["decision_id"]
    cluster_id = decision_in_store["cluster_id"]
    resp = _attempt_curation(curation_api_url, token, decision_id, cluster_id)
    assert resp.status_code == 204, (
        f"Expected HTTP 204 for curation action by reactivated curator, "
        f"got {resp.status_code}. Body: {resp.json() if resp.content else 'empty'}"
    )


@then("the retirement operation is accepted")
def then_retirement_accepted(ctx):
    status = ctx["response"].status_code
    assert status == 200, (
        f"Expected HTTP 200 for retirement operation, got {status}. "
        f"Body: {ctx.get('response_body')}"
    )


@then("the user cannot submit a re-evaluation request using their credentials")
def then_retired_curator_cannot_curate(ctx, decision_in_store, curation_api_url):
    """Retired user (is_active=False, is_verified=False) cannot perform curation."""
    token = _login_as_curator(curation_api_url)
    if token is None:
        # Cannot authenticate — correct behaviour.
        return
    decision_id = decision_in_store["decision_id"]
    cluster_id = decision_in_store["cluster_id"]
    resp = _attempt_curation(curation_api_url, token, decision_id, cluster_id)
    assert resp.status_code in (401, 403), (
        f"Expected 401 or 403 for retired curator attempting curation, "
        f"got {resp.status_code}. Body: {resp.json() if resp.content else 'empty'}"
    )


@then("the existing user action log entries referencing that user are still present and unchanged")
def then_user_action_log_preserved(mongo_db):
    count = mongo_db["user_actions"].count_documents({})
    assert count >= 1, (
        f"Expected at least 1 user_actions entry to remain after retirement, "
        f"but found {count}."
    )


@then("the cluster assignments and decision store content are not affected by the retirement")
def then_decisions_not_affected_by_retirement(mongo_db):
    """The retirement of a user must not modify the decisions collection."""
    count = mongo_db["decisions"].count_documents({})
    assert count >= 1, (
        f"Expected at least 1 decision to remain in store after retirement, "
        f"but found {count}."
    )
    doc = mongo_db["decisions"].find_one({})
    assert doc is not None
    assert doc.get("current_placement") is not None, (
        f"Expected current_placement to be intact in decisions after retirement. Doc: {doc}"
    )


@then("an error is returned to the Admin")
def then_admin_receives_error(ctx):
    status = ctx["response"].status_code
    assert status in (400, 422), (
        f"Expected HTTP 400 or 422 for invalid access modification, got {status}. "
        f"Body: {ctx.get('response_body')}"
    )


@then("the user's access state in the access registry is unchanged from before the operation")
def then_user_access_state_unchanged(curation_api_url):
    # Verify by login — the user was active (created as is_active=True).
    # If the failed PATCH left them in a broken state, login would fail.
    token = _login_as_curator(curation_api_url)
    assert token is not None, (
        "Expected curator to still be able to log in (is_active=True) after failed "
        "PATCH, but login returned no token — state may have been corrupted."
    )
