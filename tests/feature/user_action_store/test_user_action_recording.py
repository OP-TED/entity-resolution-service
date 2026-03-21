"""Step definitions for user_action_recording.feature.

Tests the domain-level UserActionFactory and the UserActionService recording
methods with mocked repositories.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from erspec.models.core import UserActionType
from pytest_bdd import given, parsers, scenario, then, when

from ers.curation.domain.exceptions import InvalidClusterError
from ers.curation.domain.models import UserActionFactory as DomainUserActionFactory
from tests.unit.factories import ClusterReferenceFactory, DecisionFactory

FEATURE = str(Path(__file__).resolve().parent / "user_action_recording.feature")


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE, "Record a recommendation for the top candidate placement")
def test_record_recommend_top():
    pass


@scenario(FEATURE, "Recorded action captures the full decision context")
def test_full_decision_context():
    pass


@scenario(FEATURE, "Record a recommendation to reject all candidates")
def test_record_recommend_rejection():
    pass


@scenario(FEATURE, "Record a recommendation for an alternative cluster placement")
def test_record_recommend_alternative():
    pass


@scenario(FEATURE, "Recommend a cluster not among the candidates is rejected")
def test_recommend_invalid_cluster():
    pass


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("a resolution decision exists for an entity mention")
def decision_exists(ctx: dict[str, Any]) -> None:
    candidates = ClusterReferenceFactory.batch(3)
    ctx["decision"] = DecisionFactory.build(
        current_placement=candidates[0],
        candidates=candidates,
    )


@given("the decision has candidate clusters with confidence scores")
def decision_has_candidates(ctx: dict[str, Any]) -> None:
    assert len(ctx["decision"].candidates) > 0


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("the decision has not been curated on its current version")
def decision_not_curated(
    ctx: dict[str, Any],
    user_action_repository: MagicMock,
) -> None:
    ctx["decision"] = ctx["decision"].model_copy(update={"updated_at": None})
    user_action_repository.has_current_action.return_value = False


@given("the decision has candidates with known confidence and similarity scores")
def decision_has_scored_candidates(ctx: dict[str, Any]) -> None:
    # Candidates are already set up in the Background; this step confirms they
    # have the expected score fields.
    for candidate in ctx["decision"].candidates:
        assert candidate.confidence_score is not None
        assert candidate.similarity_score is not None


@given("the current placement is known")
def current_placement_known(ctx: dict[str, Any]) -> None:
    assert ctx["decision"].current_placement is not None


@given(parsers.parse('the decision has an alternative candidate "{cluster_id}"'))
def decision_has_alternative(ctx: dict[str, Any], cluster_id: str) -> None:
    alternative = ClusterReferenceFactory.build(cluster_id=cluster_id)
    existing = ctx["decision"].candidates
    ctx["decision"] = ctx["decision"].model_copy(
        update={"candidates": [*existing, alternative]},
    )


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the curator recommends the top candidate placement")
def curator_recommends_top(ctx: dict[str, Any]) -> None:
    ctx["actor"] = "curator@example.com"
    ctx["user_action"] = DomainUserActionFactory.create_accept(
        actor=ctx["actor"],
        decision=ctx["decision"],
    )


@when(parsers.parse('the curator "{actor}" recommends {recommendation}'))
def curator_recommends_parametrized(
    ctx: dict[str, Any],
    actor: str,
    recommendation: str,
) -> None:
    """Dispatch step for the Scenario Outline 'Recorded action captures the full
    decision context'.  The *recommendation* value comes from the Examples table
    and determines which factory method to call.
    """
    ctx["actor"] = actor
    recommendation = recommendation.strip()

    if recommendation == "the top candidate placement":
        ctx["user_action"] = DomainUserActionFactory.create_accept(
            actor=actor, decision=ctx["decision"],
        )
    elif recommendation == "rejection of all candidates":
        ctx["user_action"] = DomainUserActionFactory.create_reject(
            actor=actor, decision=ctx["decision"],
        )
    elif recommendation == "placement in alternative cluster":
        # Pick the last candidate as the alternative for this parametrized case.
        alt_cluster_id = ctx["decision"].candidates[-1].cluster_id
        ctx["user_action"] = DomainUserActionFactory.create_assign(
            actor=actor, decision=ctx["decision"], cluster_id=alt_cluster_id,
        )
    else:
        msg = f"Unknown recommendation: {recommendation}"
        raise ValueError(msg)


@when("the curator recommends rejection of all candidates")
def curator_recommends_rejection(ctx: dict[str, Any]) -> None:
    ctx["actor"] = "curator@example.com"
    ctx["user_action"] = DomainUserActionFactory.create_reject(
        actor=ctx["actor"],
        decision=ctx["decision"],
    )


@when(
    parsers.parse('the curator recommends placement in alternative cluster "{cluster_id}"'),
)
def curator_recommends_alternative(ctx: dict[str, Any], cluster_id: str) -> None:
    ctx["actor"] = "curator@example.com"
    try:
        ctx["user_action"] = DomainUserActionFactory.create_assign(
            actor=ctx["actor"],
            decision=ctx["decision"],
            cluster_id=cluster_id,
        )
        ctx["error"] = None
    except InvalidClusterError as exc:
        ctx["user_action"] = None
        ctx["error"] = exc


@when(parsers.parse('the curator recommends placement in cluster "{cluster_id}"'))
def curator_recommends_cluster(ctx: dict[str, Any], cluster_id: str) -> None:
    ctx["actor"] = "curator@example.com"
    try:
        ctx["user_action"] = DomainUserActionFactory.create_assign(
            actor=ctx["actor"],
            decision=ctx["decision"],
            cluster_id=cluster_id,
        )
        ctx["error"] = None
    except InvalidClusterError as exc:
        ctx["user_action"] = None
        ctx["error"] = exc


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.parse('a user action is recorded with action type "{action_type}"'))
def action_recorded_with_type(ctx: dict[str, Any], action_type: str) -> None:
    type_map = {
        "accept top": UserActionType.ACCEPT_TOP,
        "reject all": UserActionType.REJECT_ALL,
        "accept alternative": UserActionType.ACCEPT_ALTERNATIVE,
    }
    assert ctx["user_action"] is not None
    assert ctx["user_action"].action_type == type_map[action_type]


@then("the selected cluster matches the decision's current placement")
def selected_cluster_matches_placement(ctx: dict[str, Any]) -> None:
    assert ctx["user_action"].selected_cluster == ctx["decision"].current_placement


@then("the action captures all candidates as a snapshot")
def action_captures_candidates(ctx: dict[str, Any]) -> None:
    assert ctx["user_action"].candidates == ctx["decision"].candidates


@then(parsers.parse('the recorded action has actor "{actor}"'))
def action_has_actor(ctx: dict[str, Any], actor: str) -> None:
    assert ctx["user_action"].actor == actor


@then("the recorded action has a timestamp")
def action_has_timestamp(ctx: dict[str, Any]) -> None:
    assert ctx["user_action"].created_at is not None


@then(parsers.parse('the recorded action has action type "{action_type}"'))
def action_has_type(ctx: dict[str, Any], action_type: str) -> None:
    type_map = {
        "accept top": UserActionType.ACCEPT_TOP,
        "reject all": UserActionType.REJECT_ALL,
        "accept alternative": UserActionType.ACCEPT_ALTERNATIVE,
    }
    assert ctx["user_action"].action_type == type_map[action_type]


@then(
    "the recorded action snapshot includes all candidates with their confidence and similarity scores",
)
def snapshot_includes_candidates_with_scores(ctx: dict[str, Any]) -> None:
    snapshot_candidates = ctx["user_action"].candidates
    decision_candidates = ctx["decision"].candidates
    assert len(snapshot_candidates) == len(decision_candidates)
    for snap, orig in zip(snapshot_candidates, decision_candidates):
        assert snap.cluster_id == orig.cluster_id
        assert snap.confidence_score == orig.confidence_score
        assert snap.similarity_score == orig.similarity_score


@then("the recorded action snapshot includes the current placement")
def snapshot_includes_current_placement(ctx: dict[str, Any]) -> None:
    action = ctx["user_action"]
    decision = ctx["decision"]
    # For accept top / accept alternative, selected_cluster should match
    # the chosen cluster.  For reject all, selected_cluster is None but
    # the candidates snapshot still includes the current placement.
    if action.selected_cluster is not None:
        assert any(
            c.cluster_id == decision.current_placement.cluster_id
            for c in action.candidates
        )
    else:
        # reject all — current placement still in snapshot candidates
        assert any(
            c.cluster_id == decision.current_placement.cluster_id
            for c in action.candidates
        )


@then("the selected cluster is empty")
def selected_cluster_is_empty(ctx: dict[str, Any]) -> None:
    assert ctx["user_action"].selected_cluster is None


@then(parsers.parse('the selected cluster is "{cluster_id}"'))
def selected_cluster_is(ctx: dict[str, Any], cluster_id: str) -> None:
    assert ctx["user_action"].selected_cluster.cluster_id == cluster_id


@then("the action is rejected because the cluster is not a valid candidate")
def action_rejected_invalid_cluster(ctx: dict[str, Any]) -> None:
    assert ctx["user_action"] is None
    assert isinstance(ctx["error"], InvalidClusterError)
