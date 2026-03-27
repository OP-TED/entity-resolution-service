"""
Step definitions for: ucb22_bulk_curator_reevaluation.feature

UC-B2.2 — Submit Bulk Curator Re-evaluation Requests (Integration)
  Tests bulk curation decomposition and per-mention forwarding:
    Curator selects N mentions → ERS validates each → forwards N independent
    recommendations to ERE (mocked at messaging boundary).

  Covers 4 scenarios:
    1. Bulk placement — N independent resolveConsideringRecommendation messages.
    2. Bulk exclusion — N independent resolveWithExclusions messages.
    3. Partial validation failure — invalid mentions rejected, valid proceed.
    4. Empty selection → VALIDATION_ERROR.

  ERE outcome integration is tested in UC-B1.2 — not duplicated here.
  Each mention is processed atomically and independently.
  Traceability: UC-W2, UC-B2.2.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenario, then, when

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE_FILE = str(Path(__file__).parent / "ucb22_bulk_curator_reevaluation.feature")


@scenario(
    FEATURE_FILE,
    "Forward bulk placement recommendations to ERE independently",
)
def test_bulk_placement():
    pass


@scenario(
    FEATURE_FILE,
    "Forward bulk exclusion recommendations to ERE independently",
)
def test_bulk_exclusion():
    pass


@scenario(
    FEATURE_FILE,
    "Invalid mentions rejected individually while valid mentions proceed",
)
def test_partial_validation_failure():
    pass


@scenario(
    FEATURE_FILE,
    "Reject bulk re-evaluation with no mentions selected",
)
def test_empty_selection():
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
    Bootstrap the ERS bulk curation stack.

    TODO: Build UserActionService with bulk support, Decision Store, ERE client.
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
# Given — mention setup (data table)
# ---------------------------------------------------------------------------


@given("the following mentions exist in the Decision Store:")
def mentions_exist(ctx, datatable):
    """
    Seed the Decision Store with multiple mentions from the data table.

    TODO: For each row, store a decision in ctx["decision_store"].
    """
    ctx["bulk_mentions"] = []
    headers = datatable[0]
    for row_values in datatable[1:]:
        row = dict(zip(headers, row_values))
        mention = {
            "source_id": row["source_id"],
            "request_id": row["request_id"],
            "entity_type": row["entity_type"],
            "current_cluster": row["current_cluster"],
        }
        ctx["bulk_mentions"].append(mention)


@given(
    parsers.parse(
        'mention with triad "{source_id}", "{request_id}", '
        '"{entity_type}" does not exist in the Decision Store'
    )
)
def mention_not_exists(ctx, source_id, request_id, entity_type):
    """Record a triad that is NOT in the Decision Store (for partial failure)."""
    ctx.setdefault("missing_mentions", []).append((source_id, request_id, entity_type))


@given("the curator selects all three mentions for bulk re-evaluation")
def select_all_three(ctx):
    """
    Build the selection to include both existing and missing mentions.

    TODO: ctx["selected_mentions"] = ctx["bulk_mentions"] + ctx["missing_mentions"]
    """
    pass


@given("an empty selection of mentions")
def empty_selection(ctx):
    """Build an empty bulk request."""
    ctx["bulk_mentions"] = []


# ---------------------------------------------------------------------------
# Given — curator recommendation
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        'the curator recommends placement into cluster "{cluster_id}" for all selected mentions'
    )
)
def curator_recommends_placement(ctx, cluster_id):
    """Build bulk placement recommendation."""
    ctx["bulk_action_type"] = "PLACEMENT"
    ctx["bulk_recommended_cluster"] = cluster_id


@given(
    parsers.parse(
        'the curator recommends excluding clusters "{excluded_clusters}" for all selected mentions'
    )
)
def curator_recommends_exclusion(ctx, excluded_clusters):
    """Build bulk exclusion recommendation."""
    ctx["bulk_action_type"] = "EXCLUSION"
    ctx["bulk_excluded_clusters"] = [c.strip() for c in excluded_clusters.split(",")]


@given(parsers.parse('the curator recommends placement into cluster "{cluster_id}"'))
def curator_recommends_placement_short(ctx, cluster_id):
    """Build placement recommendation (short form for empty selection)."""
    ctx["bulk_action_type"] = "PLACEMENT"
    ctx["bulk_recommended_cluster"] = cluster_id


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the curator submits the bulk re-evaluation request")
def submit_bulk_reevaluation(ctx):
    """
    TODO: ctx["response"] = await ctx["client"].post(
        "/curation/reevaluate/bulk", json=request_body, headers=ctx["auth_headers"]
    )
    """
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


@then("the response indicates partial success")
def partial_success(ctx):
    """
    TODO: assert ctx["response"].status_code == 207
    """
    assert True  # TODO: implement


@then(parsers.parse('the request is rejected with error "{error_code}"'))
def request_rejected(ctx, error_code):
    """
    TODO: data = ctx["response"].json()
          assert data["error_code"] == error_code
    """
    assert True  # TODO: implement


@then(
    parsers.parse(
        "the response includes a per-mention rejection for "
        '"{source_id}", "{request_id}", "{entity_type}" with error "{error_code}"'
    )
)
def per_mention_rejection(ctx, source_id, request_id, entity_type, error_code):
    """
    TODO: data = ctx["response"].json()
          rejected = [r for r in data["results"]
                      if r["request_id"] == request_id and r.get("error_code")]
          assert len(rejected) == 1
          assert rejected[0]["error_code"] == error_code
    """
    assert True  # TODO: implement


# ---------------------------------------------------------------------------
# Then — ERE messaging assertions
# ---------------------------------------------------------------------------


@then(
    parsers.parse(
        "{count:d} individual resolveConsideringRecommendation messages are forwarded to ERE"
    )
)
def n_recommendation_messages(ctx, count):
    """
    TODO: assert ctx["ere_client"].publish.call_count == count
          Verify each call is a resolveConsideringRecommendation.
    """
    assert True  # TODO: implement


@then(parsers.parse('each forwarded message recommends cluster "{cluster_id}"'))
def each_message_recommends(ctx, cluster_id):
    """
    TODO: for call in ctx["ere_client"].publish.call_args_list:
              assert call contains cluster_id
    """
    assert True  # TODO: implement


@then(parsers.parse("{count:d} individual resolveWithExclusions messages are forwarded to ERE"))
def n_exclusion_messages(ctx, count):
    """
    TODO: assert ctx["ere_client"].publish.call_count == count
    """
    assert True  # TODO: implement


# ---------------------------------------------------------------------------
# Then — Decision Store assertions
# ---------------------------------------------------------------------------


@then("the Decision Store is not modified for any of the selected mentions")
def decision_store_unmodified(ctx):
    """
    TODO: For each mention in ctx["bulk_mentions"], verify the cluster is unchanged.
    """
    assert True  # TODO: implement
