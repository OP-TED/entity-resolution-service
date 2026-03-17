"""
Step definitions for: ucb21_submit_user_reevaluation.feature

UC-B2.1 — Submit User Re-evaluation Request (Integration)
  Tests the single-mention curation flow:
    User → ERS API → validate → forward to ERE (mocked at messaging boundary)

  Covers 5 scenarios:
    1. Placement recommendation forwarded to ERE, Decision Store unchanged (Outline).
    2. Exclusion recommendation forwarded to ERE, Decision Store unchanged (Outline).
    3. Unknown mention → MENTION_NOT_FOUND, no ERE message.
    4. Invalid request fields → VALIDATION_ERROR (Outline).
    5. ERE unavailable → SERVICE_ERROR, Decision Store unchanged.

  ERE outcome integration is tested in UC-B1.2 — not duplicated here.
  ERE is mocked at the messaging boundary.
  Traceability: UC-W2, UC-B2.1.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenario, then, when

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE_FILE = str(
    Path(__file__).parent.parent.parent
    / "features"
    / "ucs"
    / "ucb21_submit_user_reevaluation.feature"
)


@scenario(FEATURE_FILE, "Forward a placement recommendation to ERE")
def test_placement_recommendation():
    pass


@scenario(FEATURE_FILE, "Forward an exclusion recommendation to ERE")
def test_exclusion_recommendation():
    pass


@scenario(FEATURE_FILE, "Reject re-evaluation for an unknown mention")
def test_unknown_mention():
    pass


@scenario(FEATURE_FILE, "Reject re-evaluation with invalid request fields")
def test_invalid_fields():
    pass


@scenario(
    FEATURE_FILE,
    "Current cluster assignment unchanged when ERE is unavailable",
)
def test_ere_unavailable():
    pass


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Shared mutable context for passing state between step functions."""
    return {}


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("the ERS system is operational")
def ers_system_operational(ctx):
    """
    Bootstrap the ERS curation stack with real components except ERE.

    TODO: Build the UserActionService, Decision Store, ERE client:
      ctx["decision_store"] = InMemoryDecisionStore()
      ctx["ere_client"] = MagicMock()
      ctx["user_action_service"] = UserActionService(
          decision_store=ctx["decision_store"],
          ere_client=ctx["ere_client"],
      )
      ctx["app"] = create_app(user_action_service=ctx["user_action_service"])
      ctx["client"] = AsyncClient(app=ctx["app"], base_url="http://test")
    """
    ctx["decision_store"] = None  # TODO: real in-memory implementation
    ctx["ere_client"] = MagicMock()
    ctx["ere_client"].publish = AsyncMock()
    ctx["client"] = None  # TODO: real AsyncClient


@given("the Decision Store is available")
def decision_store_available(ctx):
    """Default — Decision Store is healthy."""
    pass


@given("the ERE messaging boundary is available")
def ere_messaging_available(ctx):
    """Default — ERE messaging mock is ready."""
    pass


@given("the user is authenticated and authorised")
def user_authenticated(ctx):
    """
    TODO: Set up auth context / headers for the test client.
    """
    ctx["auth_headers"] = {"Authorization": "Bearer test-token"}


# ---------------------------------------------------------------------------
# Given — mention setup
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        'a mention with triad "{source_id}", "{request_id}", '
        '"{entity_type}" exists in the Decision Store'
    )
)
def mention_exists(ctx, source_id, request_id, entity_type):
    """
    Seed the Decision Store with a mention. Cluster set by next step.

    TODO: Store a decision record in ctx["decision_store"].
    """
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = entity_type


@given(parsers.parse('the current cluster assignment is "{cluster_id}"'))
def current_cluster(ctx, cluster_id):
    """
    TODO: Seed Decision Store with cluster_id for current triad.
    """
    ctx["current_cluster"] = cluster_id


@given(
    parsers.parse(
        'no mention with triad "{source_id}", "{request_id}", '
        '"{entity_type}" exists in the Decision Store'
    )
)
def mention_not_exists(ctx, source_id, request_id, entity_type):
    """Ensure the triad is NOT in the Decision Store."""
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = entity_type


# ---------------------------------------------------------------------------
# Given — user recommendation
# ---------------------------------------------------------------------------


@given(parsers.parse('the user recommends placement into cluster "{cluster_id}"'))
def recommend_placement(ctx, cluster_id):
    """Build a placement recommendation request."""
    ctx["action_type"] = "PLACEMENT"
    ctx["recommended_cluster"] = cluster_id


@given(parsers.parse('the user recommends excluding clusters "{excluded_clusters}"'))
def recommend_exclusion(ctx, excluded_clusters):
    """Build an exclusion recommendation request."""
    ctx["action_type"] = "EXCLUSION"
    ctx["excluded_clusters"] = [c.strip() for c in excluded_clusters.split(",")]


@given(parsers.parse("a re-evaluation request with {invalid_condition}"))
def invalid_reevaluation_request(ctx, invalid_condition):
    """
    Build a re-evaluation request with the specified invalid condition.

    TODO: Depending on invalid_condition, omit or corrupt the required fields.
    """
    ctx["invalid_condition"] = invalid_condition


@given("the ERE messaging boundary is unavailable")
def ere_messaging_unavailable(ctx):
    """
    TODO: ctx["ere_client"].publish = AsyncMock(
        side_effect=MessagingException("ERE unavailable")
    )
    """
    ctx["ere_unavailable"] = True


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the user submits the re-evaluation request")
def submit_reevaluation(ctx):
    """
    TODO: ctx["response"] = await ctx["client"].post(
        "/curation/reevaluate", json=request_body, headers=ctx["auth_headers"]
    )
    """
    ctx["response"] = None  # TODO: replace with real client call


@when(
    parsers.parse(
        "the user submits the re-evaluation request for triad "
        '"{source_id}", "{request_id}", "{entity_type}"'
    )
)
def submit_reevaluation_for_triad(ctx, source_id, request_id, entity_type):
    """Submit for a specific (possibly unknown) triad."""
    ctx["response"] = None  # TODO: replace with real client call


# ---------------------------------------------------------------------------
# Then — acceptance / rejection
# ---------------------------------------------------------------------------


@then("the request is accepted")
def request_accepted(ctx):
    """
    TODO: assert ctx["response"].status_code in (200, 202)
    """
    assert True  # TODO: implement


@then(parsers.parse('the request is rejected with error "{error_code}"'))
def request_rejected(ctx, error_code):
    """
    TODO: data = ctx["response"].json()
          assert data["error_code"] == error_code
    """
    assert True  # TODO: implement


# ---------------------------------------------------------------------------
# Then — ERE messaging assertions
# ---------------------------------------------------------------------------


@then(
    parsers.parse(
        "a resolveConsideringRecommendation message is forwarded to ERE "
        'for triad "{source_id}", "{request_id}", "{entity_type}"'
    )
)
def recommendation_forwarded(ctx, source_id, request_id, entity_type):
    """
    TODO: ctx["ere_client"].publish.assert_called()
          Verify the message type and triad in the call args.
    """
    assert True  # TODO: implement


@then(parsers.parse('the recommended cluster in the forwarded message is "{cluster_id}"'))
def forwarded_message_cluster(ctx, cluster_id):
    """
    TODO: Verify the recommended cluster in the ERE publish call args.
    """
    assert True  # TODO: implement


@then(
    parsers.parse(
        "a resolveWithExclusions message is forwarded to ERE "
        'for triad "{source_id}", "{request_id}", "{entity_type}"'
    )
)
def exclusion_forwarded(ctx, source_id, request_id, entity_type):
    """
    TODO: Verify the message type is resolveWithExclusions and triad matches.
    """
    assert True  # TODO: implement


@then(parsers.parse('the excluded clusters in the forwarded message are "{excluded_clusters}"'))
def forwarded_excluded_clusters(ctx, excluded_clusters):
    """
    TODO: expected = [c.strip() for c in excluded_clusters.split(",")]
          Verify excluded clusters in the ERE publish call args.
    """
    assert True  # TODO: implement


@then("no message is forwarded to ERE")
def no_ere_message(ctx):
    """
    TODO: ctx["ere_client"].publish.assert_not_called()
    """
    assert True  # TODO: implement


# ---------------------------------------------------------------------------
# Then — Decision Store assertions
# ---------------------------------------------------------------------------


@then(parsers.parse('the Decision Store still reflects "{cluster_id}" for that triad'))
def decision_store_unchanged(ctx, cluster_id):
    """
    TODO: decision = await ctx["decision_store"].get_decision_for_mention(...)
          assert decision.current_placement.cluster_id == cluster_id
    """
    assert True  # TODO: implement
