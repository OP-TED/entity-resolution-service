"""
Step definitions for: ucw4_consult_resolution_statistics.feature

UC-W4 — Consult Resolution Statistics
  Tests the read-only statistics retrieval:
    Curator → ERS API → Decision Store aggregation → response

  Covers 5 scenarios:
    1. Aggregated statistics per entity type (Outline).
    2. Zero counts when no data exists for entity type.
    3. Overview across all entity types.
    4. Read-only contract — no state modification.
    5. Decision Store unavailable → SERVICE_ERROR.

  Strictly read-only. No resolution, re-evaluation, or state modification.
  Traceability: UC-W4.
"""

from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenario, then, when

pytestmark = pytest.mark.skip(
    reason="Deferred: requires statistics endpoint (future EPIC)"
)

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE_FILE = str(Path(__file__).parent / "ucw4_consult_resolution_statistics.feature")


@scenario(
    FEATURE_FILE,
    "Retrieve aggregated statistics for a given entity type",
)
def test_statistics_per_entity_type():
    pass


@scenario(
    FEATURE_FILE,
    "Return zero counts when no data exists for the requested entity type",
)
def test_empty_entity_type():
    pass


@scenario(
    FEATURE_FILE,
    "Retrieve aggregated statistics across all entity types",
)
def test_statistics_all_types():
    pass


@scenario(
    FEATURE_FILE,
    "Statistics retrieval does not modify any system state",
)
def test_read_only_contract():
    pass


@scenario(
    FEATURE_FILE,
    "Return service error when the Decision Store is unavailable",
)
def test_decision_store_unavailable():
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
    Bootstrap the ERS statistics stack.

    TODO: Build the StatisticsService, Decision Store:
      ctx["decision_store"] = InMemoryDecisionStore()
      ctx["statistics_service"] = StatisticsService(
          decision_store=ctx["decision_store"],
      )
      ctx["app"] = create_app(statistics_service=ctx["statistics_service"])
      ctx["client"] = AsyncClient(app=ctx["app"], base_url="http://test")
    """
    ctx["decision_store"] = None  # TODO: real in-memory implementation
    ctx["client"] = None  # TODO: real AsyncClient


@given("the Decision Store is available")
def decision_store_available(ctx):
    """Default — Decision Store is healthy."""
    pass


@given("the user is authenticated and authorised")
def user_authenticated(ctx):
    """
    TODO: Set up auth context / headers for the test client.
    """
    ctx["auth_headers"] = {"Authorization": "Bearer test-token"}


# ---------------------------------------------------------------------------
# Given — Decision Store state
# ---------------------------------------------------------------------------


@given(
    parsers.parse('the Decision Store contains {count:d} mentions of entity type "{entity_type}"')
)
def decision_store_has_mentions(ctx, count, entity_type):
    """
    Seed the Decision Store with N mentions for the given entity type.

    TODO: Batch-insert N decision records with entity_type.
    """
    ctx["entity_type"] = entity_type
    ctx["expected_mention_count"] = count


@given(parsers.parse("those mentions are assigned to {count:d} distinct clusters"))
def mentions_in_n_clusters(ctx, count):
    """
    Configure the seeded mentions to be distributed across N clusters.

    TODO: Assign the seeded mentions to N distinct cluster IDs.
    """
    ctx["expected_cluster_count"] = count


@given(parsers.parse("{count:d} resolution requests were submitted in the last day"))
def recent_requests(ctx, count):
    """
    Seed recent resolution requests within the last-day window.

    TODO: Insert N request records with timestamps within the last 24h.
    """
    ctx["expected_recent_count"] = count


@given(parsers.parse('the Decision Store contains no mentions of entity type "{entity_type}"'))
def decision_store_empty_for_type(ctx, entity_type):
    """Ensure no mentions exist for the given entity type."""
    ctx["entity_type"] = entity_type


@given("the Decision Store contains mentions across multiple entity types")
def decision_store_multiple_types(ctx):
    """
    Seed the Decision Store with mentions across several entity types.

    TODO: Insert mentions for ORGANISATION, PERSON, etc.
    """
    pass


@given("the Decision Store is unavailable")
def decision_store_unavailable(ctx):
    """
    TODO: Configure the statistics service to raise ServiceException.
    """
    ctx["decision_store_unavailable"] = True


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(parsers.parse('the curator requests statistics for entity type "{entity_type}"'))
def request_statistics_for_type(ctx, entity_type):
    """
    TODO: ctx["response"] = await ctx["client"].get(
        "/statistics", params={"entity_type": entity_type},
        headers=ctx["auth_headers"]
    )
    """
    ctx["response"] = None  # TODO: replace with real client call


@when("the curator requests statistics without specifying an entity type")
def request_statistics_all(ctx):
    """
    TODO: ctx["response"] = await ctx["client"].get(
        "/statistics", headers=ctx["auth_headers"]
    )
    """
    ctx["response"] = None  # TODO: replace with real client call


# ---------------------------------------------------------------------------
# Then — statistics assertions
# ---------------------------------------------------------------------------


@then(parsers.parse("the response returns total mentions {count:d}"))
def response_total_mentions(ctx, count):
    """
    TODO: data = ctx["response"].json()
          assert data["total_mentions"] == count
    """
    assert True  # TODO: implement


@then(parsers.parse("the response returns total clusters {count:d}"))
def response_total_clusters(ctx, count):
    """
    TODO: data = ctx["response"].json()
          assert data["total_clusters"] == count
    """
    assert True  # TODO: implement


@then(parsers.parse("the response returns recent requests {count:d}"))
def response_recent_requests(ctx, count):
    """
    TODO: data = ctx["response"].json()
          assert data["recent_requests"] == count
    """
    assert True  # TODO: implement


@then("the response includes aggregated totals across all entity types")
def response_has_all_types(ctx):
    """
    TODO: data = ctx["response"].json()
          assert len(data["by_entity_type"]) > 1
    """
    assert True  # TODO: implement


@then("each entity type section includes total mentions, total clusters, and recent requests")
def each_section_has_fields(ctx):
    """
    TODO: data = ctx["response"].json()
          for section in data["by_entity_type"]:
              assert "total_mentions" in section
              assert "total_clusters" in section
              assert "recent_requests" in section
    """
    assert True  # TODO: implement


@then(parsers.parse('the response returns error "{error_code}"'))
def response_error(ctx, error_code):
    """
    TODO: data = ctx["response"].json()
          assert data["error_code"] == error_code
    """
    assert True  # TODO: implement


# ---------------------------------------------------------------------------
# Then — read-only contract
# ---------------------------------------------------------------------------


@then("no resolution request is published to the ERE")
def no_ere_publish(ctx):
    """TODO: Verify no ERE publish was called."""
    assert True  # TODO: implement


@then("no cluster assignment is written or modified in the Decision Store")
def no_decision_store_write(ctx):
    """TODO: Verify no write operations on Decision Store."""
    assert True  # TODO: implement


@then("no new resolution request is registered")
def no_request_registered(ctx):
    """TODO: Verify no request registration."""
    assert True  # TODO: implement
