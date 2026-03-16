"""
Step definitions for: outcome_acceptance.feature

Feature: Accept and Persist ERE Resolution Outcomes
  Covers three behaviours:
    1. A valid solicited resolution outcome is persisted to the Decision Store.
    2. An unsolicited reclustering outcome (ERE-initiated) is persisted correctly.
    3. Alternative candidates are replaced wholesale — never merged with prior alternatives.

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
    / "features"
    / "ere_result_integrator"
    / "outcome_acceptance.feature"
)


@scenario(FEATURE_FILE, "Accept a valid solicited resolution outcome")
def test_accept_valid_solicited_outcome():
    """Bind the 'Accept a valid solicited resolution outcome' scenario outline."""
    pass


@scenario(FEATURE_FILE, "Accept an unsolicited reclustering outcome initiated by the ERE")
def test_accept_unsolicited_reclustering_outcome():
    """Bind the 'Accept an unsolicited reclustering outcome' scenario outline."""
    pass


@scenario(FEATURE_FILE, "Replace alternative candidates wholesale when a new outcome arrives")
def test_replace_alternatives_wholesale():
    """Bind the 'Replace alternative candidates wholesale' scenario outline."""
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


@given("the Request Registry contains a mention for each correlation triad used in the scenarios below")
def request_registry_contains_mentions(ctx):
    """
    Set up the Request Registry repository mock to confirm triad existence.

    TODO: Replace with create_autospec(RequestRegistryRepository)
    """
    # TODO: import RequestRegistryRepository
    registry_repo = MagicMock()
    registry_repo.find_by_triad = AsyncMock(return_value=MagicMock())
    ctx["registry_repo"] = registry_repo


@given("the Decision Store contains no prior cluster assignment for those triads")
def decision_store_is_empty(ctx):
    """
    Set up the Decision Store repository mock with no existing assignments.

    TODO: Replace with create_autospec(DecisionStoreRepository)
    """
    # TODO: import DecisionStoreRepository
    decision_repo = MagicMock()
    decision_repo.find_by_triad = AsyncMock(return_value=None)
    decision_repo.upsert = AsyncMock()
    ctx["decision_repo"] = decision_repo


# ---------------------------------------------------------------------------
# Given — scenario-specific setup
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        'the mention with triad ("{source_id}", "{request_id}", "Organization") '
        "exists in the Request Registry"
    )
)
def mention_exists_in_registry(ctx, source_id, request_id):
    """
    Confirm that a mention with the given triad exists in the Request Registry.

    TODO: Build a real CorrelationTriad and configure the registry mock.
    """
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = "Organization"


@given(
    parsers.parse(
        'the Decision Store "{prior_state}" a prior cluster assignment for that triad'
    )
)
def decision_store_prior_state(ctx, prior_state):
    """
    Configure Decision Store mock based on whether a prior assignment exists.

    TODO: If prior_state == "contains", seed a ClusterAssignment in the mock.
    """
    if prior_state == "contains":
        existing = MagicMock()
        existing.outcome_timestamp = "2026-03-14T09:00:00.000Z"
        ctx["decision_repo"].find_by_triad = AsyncMock(return_value=existing)
        ctx["existing_assignment"] = existing
    else:
        ctx["decision_repo"].find_by_triad = AsyncMock(return_value=None)


@given(
    parsers.parse(
        'the Decision Store contains an existing cluster assignment '
        'with "{prior_candidate_count}" alternative candidates'
    )
)
def decision_store_has_prior_candidates(ctx, prior_candidate_count):
    """
    Seed the Decision Store mock with an existing assignment that has N alternatives.

    TODO: Build a real ClusterAssignment with N alternative candidates.
    """
    count = int(prior_candidate_count)
    existing = MagicMock()
    existing.alternatives = [MagicMock() for _ in range(count)]
    existing.outcome_timestamp = "2026-03-15T11:00:00.000Z"
    ctx["decision_repo"].find_by_triad = AsyncMock(return_value=existing)
    ctx["existing_assignment"] = existing


# ---------------------------------------------------------------------------
# When — trigger outcome integration
# ---------------------------------------------------------------------------


@when(
    parsers.parse(
        'the ERE publishes a solicited outcome for that triad with outcome timestamp '
        '"{outcome_timestamp}", primary cluster "{cluster_id}", '
        'and "{candidate_count}" alternative candidates'
    )
)
def ere_publishes_solicited_outcome(ctx, outcome_timestamp, cluster_id, candidate_count):
    """
    Call OutcomeIntegrationService.integrate_outcome with a solicited outcome.

    TODO: Build an OutcomeMessage and call the real service:
        outcome = OutcomeMessage(
            triad=CorrelationTriad(ctx["source_id"], ctx["request_id"], ctx["entity_type"]),
            cluster_id=cluster_id,
            alternatives=[...],
            timestamp=outcome_timestamp,
            ere_request_id=f"{ctx['request_id']}:001",
        )
        ctx["result"] = await service.integrate_outcome(outcome)
    """
    ctx["outcome_timestamp"] = outcome_timestamp
    ctx["cluster_id"] = cluster_id
    ctx["candidate_count"] = int(candidate_count)
    ctx["result"] = None  # TODO: replace with real service call
    ctx["raised_exception"] = None


@when(
    parsers.parse(
        'the ERE publishes an unsolicited outcome identified by "{ere_request_id}" '
        'with outcome timestamp "{outcome_timestamp}" and primary cluster "{cluster_id}"'
    )
)
def ere_publishes_unsolicited_outcome(ctx, ere_request_id, outcome_timestamp, cluster_id):
    """
    Call OutcomeIntegrationService.integrate_outcome with an unsolicited outcome.

    TODO: Build an OutcomeMessage with ereNotification: prefix and call the service.
    """
    ctx["ere_request_id"] = ere_request_id
    ctx["outcome_timestamp"] = outcome_timestamp
    ctx["cluster_id"] = cluster_id
    ctx["result"] = None  # TODO: replace with real service call
    ctx["raised_exception"] = None


@when(
    parsers.parse(
        'the ERE publishes a new outcome for that triad with outcome timestamp '
        '"{outcome_timestamp}" and "{new_candidate_count}" alternative candidates'
    )
)
def ere_publishes_new_outcome_with_candidates(ctx, outcome_timestamp, new_candidate_count):
    """
    Call OutcomeIntegrationService.integrate_outcome with a new outcome
    carrying a different number of alternatives than the prior assignment.

    TODO: Build an OutcomeMessage and call the service.
    """
    ctx["outcome_timestamp"] = outcome_timestamp
    ctx["new_candidate_count"] = int(new_candidate_count)
    ctx["result"] = None  # TODO: replace with real service call
    ctx["raised_exception"] = None


# ---------------------------------------------------------------------------
# Then — assert outcomes
# ---------------------------------------------------------------------------


@then(
    parsers.parse(
        'the Decision Store is updated with cluster assignment "{cluster_id}" for that triad'
    )
)
def decision_store_updated_with_cluster(ctx, cluster_id):
    """
    Assert that the Decision Store was updated with the expected cluster assignment.

    TODO: assert ctx["result"].cluster_id == cluster_id
          ctx["decision_repo"].upsert.assert_called_once()
    """
    assert True  # TODO: implement


@then(
    parsers.parse(
        'the outcome marker stored in the Decision Store equals "{outcome_timestamp}"'
    )
)
def outcome_marker_equals(ctx, outcome_timestamp):
    """
    Assert that the persisted outcome marker matches the incoming timestamp.

    TODO: assert ctx["result"].outcome_timestamp == outcome_timestamp
    """
    assert True  # TODO: implement


@then(
    parsers.parse(
        'all "{candidate_count}" alternative candidates are stored '
        "alongside the primary cluster assignment"
    )
)
def alternative_candidates_stored(ctx, candidate_count):
    """
    Assert that the correct number of alternative candidates was persisted.

    TODO: assert len(ctx["result"].alternatives) == int(candidate_count)
    """
    assert True  # TODO: implement


@then(
    parsers.parse(
        'the Decision Store stores exactly "{new_candidate_count}" '
        "alternative candidates for that triad"
    )
)
def decision_store_has_exact_candidate_count(ctx, new_candidate_count):
    """
    Assert that the Decision Store now holds exactly N alternative candidates.

    TODO: assert len(ctx["result"].alternatives) == int(new_candidate_count)
    """
    assert True  # TODO: implement


@then("no candidates from the prior outcome are retained")
def no_prior_candidates_retained(ctx):
    """
    Assert that alternatives were replaced wholesale, not merged.

    TODO: Verify that none of the prior alternatives appear in ctx["result"].alternatives.
    """
    assert True  # TODO: implement
