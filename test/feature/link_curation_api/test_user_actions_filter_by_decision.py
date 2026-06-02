"""Step definitions for user_actions_filter_by_decision.feature.

BDD coverage for Phase 3 of TEDSWS-528: filter /api/v1/curation/user-actions
by decision_id to retrieve the curator action timeline for a single decision.
"""

from pathlib import Path
from typing import Any

from erspec.models.core import UserActionType
from pytest_bdd import given, scenario, then, when
from starlette.testclient import TestClient

from ers.commons.domain.data_transfer_objects import CursorPage
from ers.curation.domain.data_transfer_objects import (
    ActorSummary,
    EntityMentionPreview,
    UserActionSummary,
)
from test.unit.factories import DecisionFactory, UserActionFactory

FEATURE = str(Path(__file__).resolve().parent / "user_actions_filter_by_decision.feature")

USER_ACTIONS_URL = "/api/v1/user-actions"


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE, "Filter by decision_id returns the entity's full curator timeline")
def test_filter_by_decision_id_returns_timeline():
    pass


@scenario(FEATURE, "Decision without user_actions returns an empty page")
def test_decision_without_actions_returns_empty_page():
    pass


@scenario(FEATURE, "decision_id filter composes with action_type filter")
def test_decision_id_composes_with_action_type_filter():
    pass


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("a decision has 3 user_actions recorded", target_fixture="ctx")
def decision_with_three_actions(
    ctx: dict[str, Any],
    decision_repository: Any,
    user_action_repository: Any,
    user_repository: Any,
    entity_mention_repository: Any,
) -> dict[str, Any]:
    """Set up a decision and mock the repository to return 3 actions for it."""
    decision = DecisionFactory.build()
    decision_repository.find_by_id.return_value = decision
    user_repository.find_by_ids.return_value = []

    actions = [
        UserActionFactory.build(about_entity_mention=decision.about_entity_mention)
        for _ in range(3)
    ]
    summaries = [
        UserActionSummary(
            id=a.id,
            about_entity_mention=EntityMentionPreview(identified_by=a.about_entity_mention),
            candidates=a.candidates,
            selected_cluster=a.selected_cluster,
            action_type=a.action_type,
            actor=ActorSummary(id=a.actor, email=f"{a.actor}@example.com"),
            created_at=a.created_at,
            metadata=a.metadata,
        )
        for a in actions
    ]
    user_action_repository.find_with_cursor.return_value = CursorPage(
        results=actions, count=3, next_cursor=None
    )
    entity_mention_repository.find_by_identifiers.return_value = []

    ctx["decision_id"] = decision.id
    ctx["expected_count"] = 3
    ctx["summaries"] = summaries
    return ctx


@given("a decision has no user_actions", target_fixture="ctx")
def decision_with_no_actions(
    ctx: dict[str, Any],
    decision_repository: Any,
    user_action_repository: Any,
    entity_mention_repository: Any,
    user_repository: Any,
) -> dict[str, Any]:
    """Set up a decision with no associated user actions."""
    decision = DecisionFactory.build()
    decision_repository.find_by_id.return_value = decision
    user_action_repository.find_with_cursor.return_value = CursorPage(
        results=[], count=0, next_cursor=None
    )
    entity_mention_repository.find_by_identifiers.return_value = []
    user_repository.find_by_ids.return_value = []

    ctx["decision_id"] = decision.id
    ctx["expected_count"] = 0
    return ctx


@given("a decision has actions of type ACCEPT_TOP and REJECT_ALL", target_fixture="ctx")
def decision_with_mixed_actions(
    ctx: dict[str, Any],
    decision_repository: Any,
    user_action_repository: Any,
    entity_mention_repository: Any,
    user_repository: Any,
) -> dict[str, Any]:
    """Set up a decision with two action types; the repo mock returns only ACCEPT_TOP
    (simulating that the action_type filter was applied at the DB layer).
    """
    decision = DecisionFactory.build()
    decision_repository.find_by_id.return_value = decision

    accept_action = UserActionFactory.build(
        about_entity_mention=decision.about_entity_mention,
        action_type=UserActionType.ACCEPT_TOP,
    )
    user_action_repository.find_with_cursor.return_value = CursorPage(
        results=[accept_action], count=1, next_cursor=None
    )
    entity_mention_repository.find_by_identifiers.return_value = []
    user_repository.find_by_ids.return_value = []

    ctx["decision_id"] = decision.id
    ctx["expected_count"] = 1
    return ctx


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("I GET /api/v1/curation/user-actions with decision_id filter", target_fixture="response")
def get_user_actions_filtered_by_decision(
    client: TestClient,
    ctx: dict[str, Any],
) -> Any:
    return client.get(USER_ACTIONS_URL, params={"decision_id": ctx["decision_id"]})


@when(
    "I GET /api/v1/curation/user-actions with decision_id and action_type=ACCEPT_TOP",
    target_fixture="response",
)
def get_user_actions_filtered_by_decision_and_type(
    client: TestClient,
    ctx: dict[str, Any],
) -> Any:
    return client.get(
        USER_ACTIONS_URL,
        params={"decision_id": ctx["decision_id"], "action_type": "ACCEPT_TOP"},
    )


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the response contains exactly those 3 actions")
def response_contains_three_actions(response: Any, ctx: dict[str, Any]) -> None:
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["count"] == ctx["expected_count"]
    assert len(data["results"]) == ctx["expected_count"]


@then("the response contains 0 results")
def response_contains_no_results(response: Any) -> None:
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["count"] == 0
    assert data["results"] == []


@then("only the ACCEPT_TOP action is returned")
def only_accept_top_returned(response: Any, ctx: dict[str, Any]) -> None:
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["count"] == ctx["expected_count"]
    assert len(data["results"]) == ctx["expected_count"]
    for result in data["results"]:
        assert result["action_type"] == UserActionType.ACCEPT_TOP.value
