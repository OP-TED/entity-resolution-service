"""
Step definitions for: deduplication_and_staleness.feature

Feature: Deduplicate ERE Outcomes Using Latest Assignment Wins
  Covers two behaviours:
    1. An outcome whose timestamp does not advance the stored marker is ignored silently.
    2. When outcomes arrive out of order, only the one with the latest marker survives.

  These steps call the OutcomeIntegrationService with mocked repositories.
  No real MongoDB or Redis connection is required for unit-level BDD scenarios.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenario, then, when

# ---------------------------------------------------------------------------
# Scenario bindings — link each scenario title to its .feature file.
# ---------------------------------------------------------------------------

FEATURE_FILE = str(
    Path(__file__).parent.parent.parent
    / "feature"
    / "ere_result_integrator"
    / "deduplication_and_staleness.feature"
)


@scenario(FEATURE_FILE, "Ignore an outcome whose timestamp does not advance the stored marker")
def test_ignore_stale_outcome():
    """Bind the 'Ignore an outcome whose timestamp does not advance the stored marker' outline."""
    pass


@scenario(FEATURE_FILE, "Only the latest outcome survives when arrivals are out of order")
def test_out_of_order_arrivals():
    """Bind the 'Only the latest outcome survives when arrivals are out of order' scenario."""
    pass


# ---------------------------------------------------------------------------
# Shared context container
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Shared mutable context for passing state between step functions."""
    return {}


# ---------------------------------------------------------------------------
# Background steps
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        "the Request Registry contains a mention with triad "
        '("{source_id}", "{request_id}", "Organization")'
    )
)
def request_registry_contains_mention(ctx, source_id, request_id):
    """
    Set up the Request Registry mock to confirm the triad exists.

    TODO: Replace with create_autospec(RequestRegistryRepository)
    """
    registry_repo = MagicMock()
    registry_repo.find_by_triad = AsyncMock(return_value=MagicMock())
    ctx["registry_repo"] = registry_repo
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = "Organization"


@given(
    parsers.parse(
        "the Decision Store contains a cluster assignment for that triad "
        'with outcome marker "{outcome_marker}"'
    )
)
def decision_store_has_assignment(ctx, outcome_marker):
    """
    Seed the Decision Store mock with an existing assignment at the given timestamp.

    TODO: Replace with create_autospec(DecisionStoreRepository)
    """
    decision_repo = MagicMock()
    existing = MagicMock()
    existing.outcome_timestamp = outcome_marker
    decision_repo.find_by_triad = AsyncMock(return_value=existing)
    decision_repo.upsert = AsyncMock()
    ctx["decision_repo"] = decision_repo
    ctx["stored_marker"] = outcome_marker
    ctx["existing_assignment"] = existing


# ---------------------------------------------------------------------------
# Given — scenario-specific setup
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        "the Decision Store is empty for a mention with triad "
        '("{source_id}", "{request_id}", "Organization")'
    )
)
def decision_store_empty_for_triad(ctx, source_id, request_id):
    """
    Configure the Decision Store mock to have no assignment for this triad.

    TODO: Ensure registry also knows about this triad.
    """
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = "Organization"
    if "decision_repo" not in ctx:
        ctx["decision_repo"] = MagicMock()
    ctx["decision_repo"].find_by_triad = AsyncMock(return_value=None)
    ctx["decision_repo"].upsert = AsyncMock()


# ---------------------------------------------------------------------------
# When — trigger outcome delivery
# ---------------------------------------------------------------------------


@when(
    parsers.parse(
        "the ERE delivers an outcome for that triad with outcome marker "
        '"{incoming_timestamp}" and cluster "{incoming_cluster}"'
    )
)
def ere_delivers_outcome(ctx, incoming_timestamp, incoming_cluster):
    """
    Call OutcomeIntegrationService.integrate_outcome and capture the result.

    TODO: Build an OutcomeMessage and call the real service:
        outcome = OutcomeMessage(
            triad=CorrelationTriad(ctx["source_id"], ctx["request_id"], ctx["entity_type"]),
            cluster_id=incoming_cluster,
            timestamp=incoming_timestamp,
        )
        ctx["result"] = await service.integrate_outcome(outcome)
    """
    ctx["incoming_timestamp"] = incoming_timestamp
    ctx["incoming_cluster"] = incoming_cluster
    ctx["result"] = None  # TODO: replace with real service call
    ctx["raised_exception"] = None


@when("the ERE delivers outcomes for that triad in this order:")
def ere_delivers_outcomes_in_order(ctx, datatable):
    """
    Deliver multiple outcomes sequentially and capture the final state.

    The datatable contains rows with | outcome_marker | cluster_id |.

    TODO: For each row, build an OutcomeMessage and call service.integrate_outcome.
          Track which were accepted vs rejected.
    """
    ctx["delivery_sequence"] = []
    headers = datatable[0]
    for row_values in datatable[1:]:
        row = dict(zip(headers, row_values))
        ctx["delivery_sequence"].append(
            {
                "outcome_marker": row["outcome_marker"],
                "cluster_id": row["cluster_id"],
            }
        )
    # TODO: Process each outcome through the service sequentially
    ctx["result"] = None
    ctx["raised_exception"] = None


# ---------------------------------------------------------------------------
# Then — assert outcomes
# ---------------------------------------------------------------------------


@then("the outcome is ignored without modifying the Decision Store")
def outcome_ignored(ctx):
    """
    Assert that the stale/duplicate outcome was rejected and no write occurred.

    TODO: ctx["decision_repo"].upsert.assert_not_called()
    """
    assert True  # TODO: implement


@then(
    parsers.parse(
        "the Decision Store still holds the cluster assignment "
        'with outcome marker "{expected_marker}"'
    )
)
def decision_store_unchanged(ctx, expected_marker):
    """
    Assert that the Decision Store assignment is unchanged from the stored marker.

    TODO: stored = await ctx["decision_repo"].find_by_triad(...)
          assert stored.outcome_timestamp == expected_marker
    """
    assert True  # TODO: implement


@then(
    parsers.parse('the Decision Store holds cluster assignment "{expected_cluster}" for that triad')
)
def decision_store_holds_cluster(ctx, expected_cluster):
    """
    Assert that after processing all outcomes, only the expected cluster survives.

    TODO: stored = await ctx["decision_repo"].find_by_triad(...)
          assert stored.cluster_id == expected_cluster
    """
    assert True  # TODO: implement
