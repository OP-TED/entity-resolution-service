"""Step definitions for user_action_idempotency.feature.

Regression tests for TEDSWS-522: the idempotency guard in
_check_not_already_curated must fire even when decision.updated_at is None
(i.e., the decision has never been re-integrated by ERE).
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pytest_bdd import given, scenario, then, when
from starlette.testclient import TestClient

from test.unit.factories import DecisionFactory

FEATURE = str(Path(__file__).resolve().parent / "user_action_idempotency.feature")

DECISIONS_URL = "/api/v1/curation/decisions"


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE, "Cannot re-accept a fresh decision (TEDSWS-522 regression)")
def test_cannot_re_accept_fresh_decision():
    pass


@scenario(FEATURE, "Cannot double-act on the same fresh placement")
def test_cannot_double_reject_fresh_decision():
    pass


@scenario(FEATURE, "New action allowed after ERE re-integration advances updated_at")
def test_new_action_allowed_after_reintegration():
    pass


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(
    "a fresh decision with no prior ERE integration and an accept already recorded",
    target_fixture="ctx",
)
def fresh_decision_with_accept_recorded(
    ctx: dict[str, Any],
    decision_repository: Any,
    user_action_repository: Any,
) -> dict[str, Any]:
    """Set up a decision that has never been re-integrated (updated_at=None)
    and whose action trail already contains an accept.

    TEDSWS-522: the idempotency guard must fire for this case.
    """
    decision = DecisionFactory.build(id="fresh-decision-1", updated_at=None)
    decision_repository.find_by_id.return_value = decision
    # Simulate the atomic claim losing the race (placement already claimed).
    decision_repository.record_review.return_value = False
    ctx["decision_id"] = "fresh-decision-1"
    return ctx


@given(
    "a fresh decision with no prior ERE integration and a reject already recorded",
    target_fixture="ctx",
)
def fresh_decision_with_reject_recorded(
    ctx: dict[str, Any],
    decision_repository: Any,
    user_action_repository: Any,
) -> dict[str, Any]:
    """Set up a decision that has never been re-integrated (updated_at=None)
    and whose action trail already contains a reject.
    """
    decision = DecisionFactory.build(id="fresh-decision-2", updated_at=None)
    decision_repository.find_by_id.return_value = decision
    decision_repository.record_review.return_value = False
    ctx["decision_id"] = "fresh-decision-2"
    return ctx


@given("a decision whose updated_at has advanced after ERE re-integration")
def decision_after_reintegration(
    ctx: dict[str, Any],
    decision_repository: Any,
    user_action_repository: Any,
) -> None:
    """Set up a decision that has been re-integrated: updated_at is not None."""
    decision = DecisionFactory.build(
        id="reintegrated-decision-1",
        updated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    decision_repository.find_by_id.return_value = decision
    ctx["decision_id"] = "reintegrated-decision-1"


@given("no action has been recorded since the latest re-integration")
def no_action_since_reintegration(
    decision_repository: Any, user_action_repository: Any
) -> None:
    """No action exists in the trail after updated_at — the atomic claim succeeds."""
    decision_repository.record_review.return_value = True
    user_action_repository.save.return_value = None


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(
    "the curator attempts to accept the same decision again",
    target_fixture="response",
)
def attempt_accept_again(
    client: TestClient,
    ctx: dict[str, Any],
) -> Any:
    return client.post(f"{DECISIONS_URL}/{ctx['decision_id']}/accept")


@when(
    "the curator attempts to reject the same decision again",
    target_fixture="response",
)
def attempt_reject_again(
    client: TestClient,
    ctx: dict[str, Any],
) -> Any:
    return client.post(f"{DECISIONS_URL}/{ctx['decision_id']}/reject")


@when(
    "the curator accepts the re-integrated decision",
    target_fixture="response",
)
def accept_reintegrated_decision(
    client: TestClient,
    ctx: dict[str, Any],
) -> Any:
    return client.post(f"{DECISIONS_URL}/{ctx['decision_id']}/accept")


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the system responds with a conflict error indicating already curated")
def conflict_already_curated(response: Any) -> None:
    assert response.status_code == 409


@then("the recommendation is recorded")
def recommendation_recorded(response: Any) -> None:
    assert response.status_code == 204
    assert response.content == b""
