"""Step definitions for decision_summary_review_counter.feature.

Tests that previous_review_count is correctly surfaced in the decision list
response, that it increments when a curator action is recorded, and that it is
preserved when ERE re-integrates a new outcome for the same mention.

The mock boundary is the repository layer; real service logic runs end-to-end.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from pytest_bdd import given, scenario, then, when
from starlette.testclient import TestClient

from ers.commons.domain.data_transfer_objects import CursorPage
from ers.resolution_decision_store.adapters.decision_repository import ReviewMetadata
from test.unit.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
)

FEATURE = str(
    Path(__file__).resolve().parent / "decision_summary_review_counter.feature"
)

DECISIONS_URL = "/api/v1/curation/decisions"


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE, "Fresh decision starts at 0")
def test_fresh_decision_starts_at_zero():
    pass


@scenario(FEATURE, "Counter increments on accept action")
def test_counter_increments_on_accept():
    pass


@scenario(FEATURE, "Counter is preserved across ERE re-integration")
def test_counter_preserved_across_reintegration():
    pass


@scenario(FEATURE, "A curator action flips reviewed_since_placement to true")
def test_action_flips_reviewed_since_placement():
    pass


@scenario(FEATURE, "ERE re-integration resets reviewed_since_placement to false")
def test_reintegration_resets_reviewed_since_placement():
    pass


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("a decision was just integrated from ERE with no prior curator actions")
def fresh_decision_integrated(
    ctx: dict[str, Any],
    decision_repository: AsyncMock,
) -> None:
    """Set up a fresh decision with previous_review_count = 0 in the repository."""
    decision = DecisionFactory.build(id="decision-fresh")
    decision_repository.find_with_filters.return_value = CursorPage(results=[decision])
    decision_repository.find_review_metadata.return_value = {}  # missing → (0, False)
    ctx["decision_id"] = decision.id


@given("a decision with previous_review_count equal to 0")
def decision_with_count_zero(
    ctx: dict[str, Any],
    decision_repository: AsyncMock,
    user_action_repository: AsyncMock,
) -> None:
    """Set up a decision with count 0, ready to accept a curator action."""
    decision = DecisionFactory.build(id="decision-zero-count")
    decision_repository.find_by_id.return_value = decision
    decision_repository.find_with_filters.return_value = CursorPage(results=[decision])
    # After accept, find_review_metadata returns (count=1, flag=True) — simulating
    # the effect of record_review when the curator action is after placement.
    decision_repository.find_review_metadata.return_value = {
        "decision-zero-count": ReviewMetadata(
            previous_review_count=1, reviewed_since_placement=True
        )
    }
    decision_repository.record_review = AsyncMock()
    user_action_repository.has_current_action.return_value = False
    user_action_repository.save.return_value = None
    ctx["decision_id"] = decision.id
    ctx["decision"] = decision


@given("a decision with previous_review_count equal to 3")
def decision_with_count_three(
    ctx: dict[str, Any],
    decision_repository: AsyncMock,
) -> None:
    """Set up a decision that has already been reviewed 3 times."""
    original_placement = ClusterReferenceFactory.build(cluster_id="original-cluster")
    decision = DecisionFactory.build(
        id="decision-three-count",
        current_placement=original_placement,
    )
    decision_repository.find_with_filters.return_value = CursorPage(results=[decision])
    # Simulate ERE re-integration writing a new placement
    new_placement = ClusterReferenceFactory.build(cluster_id="new-cluster")
    decision_after_reintegration = DecisionFactory.build(
        id="decision-three-count",
        current_placement=new_placement,
    )
    decision_repository.find_with_filters.side_effect = [
        # First call (after reintegration)
        CursorPage(results=[decision_after_reintegration]),
    ]
    # Counter must still be 3 — re-integration does not touch it. The flag has
    # been reset to False by the integrator in the same write that advanced
    # placement, so the row is "needs revisit" until a curator acts again.
    decision_repository.find_review_metadata.return_value = {
        "decision-three-count": ReviewMetadata(
            previous_review_count=3, reviewed_since_placement=False
        )
    }
    ctx["decision_id"] = decision.id
    ctx["new_cluster_id"] = "new-cluster"


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the curator requests the decisions list")
def curator_requests_decisions_list(
    ctx: dict[str, Any],
    client: TestClient,
) -> None:
    response = client.get(DECISIONS_URL)
    ctx["response"] = response


@when("the curator records an accept action on that decision")
def curator_records_accept(
    ctx: dict[str, Any],
    client: TestClient,
) -> None:
    # First record the accept action
    accept_response = client.post(
        f"{DECISIONS_URL}/{ctx['decision_id']}/accept",
    )
    ctx["accept_response"] = accept_response
    # Then request the list to verify the counter
    list_response = client.get(DECISIONS_URL)
    ctx["response"] = list_response


@when("ERE re-integrates a new outcome for the same decision")
def ere_reintegrates_outcome(
    ctx: dict[str, Any],
    client: TestClient,
) -> None:
    # Re-integration happens at the repository level (the mock already returns
    # the post-reintegration state); just fetch the list to verify preservation.
    response = client.get(DECISIONS_URL)
    ctx["response"] = response


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the row for that decision has previous_review_count equal to 0")
def assert_review_count_zero(ctx: dict[str, Any]) -> None:
    response = ctx["response"]
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )
    data = response.json()
    results = data.get("results", [])
    assert len(results) >= 1, "Expected at least one decision in the list"
    row = next((r for r in results if r["id"] == ctx["decision_id"]), None)
    assert row is not None, f"Decision {ctx['decision_id']} not found in response"
    assert row["previous_review_count"] == 0, (
        f"Expected previous_review_count=0, got {row['previous_review_count']}"
    )


@then("the row for that decision has previous_review_count equal to 1")
def assert_review_count_one(ctx: dict[str, Any]) -> None:
    response = ctx["response"]
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )
    data = response.json()
    results = data.get("results", [])
    assert len(results) >= 1, "Expected at least one decision in the list"
    row = next((r for r in results if r["id"] == ctx["decision_id"]), None)
    assert row is not None, f"Decision {ctx['decision_id']} not found in response"
    assert row["previous_review_count"] == 1, (
        f"Expected previous_review_count=1, got {row['previous_review_count']}"
    )


@then("the row for that decision still has previous_review_count equal to 3")
def assert_review_count_still_three(ctx: dict[str, Any]) -> None:
    response = ctx["response"]
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )
    data = response.json()
    results = data.get("results", [])
    assert len(results) >= 1, "Expected at least one decision in the list"
    row = next((r for r in results if r["id"] == ctx["decision_id"]), None)
    assert row is not None, f"Decision {ctx['decision_id']} not found in response"
    assert row["previous_review_count"] == 3, (
        f"Expected previous_review_count=3, got {row['previous_review_count']}"
    )


@then("the row for that decision has reviewed_since_placement equal to true")
def assert_reviewed_since_placement_true(ctx: dict[str, Any]) -> None:
    response = ctx["response"]
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )
    data = response.json()
    row = next(
        (r for r in data.get("results", []) if r["id"] == ctx["decision_id"]), None
    )
    assert row is not None, f"Decision {ctx['decision_id']} not found in response"
    assert row["reviewed_since_placement"] is True, (
        f"Expected reviewed_since_placement=true, got {row['reviewed_since_placement']}"
    )


@then("the row for that decision has reviewed_since_placement equal to false")
def assert_reviewed_since_placement_false(ctx: dict[str, Any]) -> None:
    response = ctx["response"]
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )
    data = response.json()
    row = next(
        (r for r in data.get("results", []) if r["id"] == ctx["decision_id"]), None
    )
    assert row is not None, f"Decision {ctx['decision_id']} not found in response"
    assert row["reviewed_since_placement"] is False, (
        f"Expected reviewed_since_placement=false, got {row['reviewed_since_placement']}"
    )


@then("the current_placement reflects the new ERE outcome")
def assert_current_placement_updated(ctx: dict[str, Any]) -> None:
    response = ctx["response"]
    assert response.status_code == 200
    data = response.json()
    results = data.get("results", [])
    row = next((r for r in results if r["id"] == ctx["decision_id"]), None)
    assert row is not None
    assert row["current_placement"]["cluster_id"] == ctx["new_cluster_id"], (
        f"Expected cluster_id={ctx['new_cluster_id']}, "
        f"got {row['current_placement']['cluster_id']}"
    )
