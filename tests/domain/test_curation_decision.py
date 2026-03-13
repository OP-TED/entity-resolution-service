import pytest
from erspec.models.core import UserActionType

from ers.domain.exceptions import InvalidClusterError
from ers.domain.models import UserActionFactory


class TestCreateAccept:
    def test_creates_user_action_with_accept_top_type(self, decision_with_candidates):
        action = UserActionFactory.create_accept(
            actor="curator-1", decision=decision_with_candidates
        )

        assert action.action_type == UserActionType.ACCEPT_TOP

    def test_selected_cluster_is_current_placement(self, decision_with_candidates):
        action = UserActionFactory.create_accept(
            actor="curator-1", decision=decision_with_candidates
        )

        assert action.selected_cluster == decision_with_candidates.current_placement

    def test_preserves_candidates_from_decision(self, decision_with_candidates):
        action = UserActionFactory.create_accept(
            actor="curator-1", decision=decision_with_candidates
        )

        assert action.candidates == decision_with_candidates.candidates

    def test_sets_actor(self, decision_with_candidates):
        action = UserActionFactory.create_accept(
            actor="curator-1", decision=decision_with_candidates
        )

        assert action.actor == "curator-1"

    def test_sets_about_entity_mention(self, decision_with_candidates):
        action = UserActionFactory.create_accept(
            actor="curator-1", decision=decision_with_candidates
        )

        assert (
            action.about_entity_mention == decision_with_candidates.about_entity_mention
        )


class TestCreateReject:
    def test_creates_user_action_with_reject_all_type(self, decision_with_candidates):
        action = UserActionFactory.create_reject(
            actor="curator-1", decision=decision_with_candidates
        )

        assert action.action_type == UserActionType.REJECT_ALL

    def test_selected_cluster_is_none(self, decision_with_candidates):
        action = UserActionFactory.create_reject(
            actor="curator-1", decision=decision_with_candidates
        )

        assert action.selected_cluster is None


class TestCreateAssign:
    def test_creates_user_action_with_accept_alternative_type(
        self, decision_with_candidates
    ):
        target_id = decision_with_candidates.candidates[1].cluster_id

        action = UserActionFactory.create_assign(
            actor="curator-1",
            decision=decision_with_candidates,
            cluster_id=target_id,
        )

        assert action.action_type == UserActionType.ACCEPT_ALTERNATIVE

    def test_selected_cluster_matches_target(self, decision_with_candidates):
        target = decision_with_candidates.candidates[1]

        action = UserActionFactory.create_assign(
            actor="curator-1",
            decision=decision_with_candidates,
            cluster_id=target.cluster_id,
        )

        assert action.selected_cluster == target

    def test_invalid_cluster_raises_error(self, decision_with_candidates):
        with pytest.raises(InvalidClusterError) as exc_info:
            UserActionFactory.create_assign(
                actor="curator-1",
                decision=decision_with_candidates,
                cluster_id="nonexistent-cluster",
            )

        assert exc_info.value.cluster_id == "nonexistent-cluster"
        assert exc_info.value.decision_id == decision_with_candidates.id
