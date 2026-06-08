"""Unit tests for the outcome-equality helper."""
from datetime import UTC, datetime

from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers.resolution_decision_store.domain.outcome import is_same_outcome


def _identifier() -> EntityMentionIdentifier:
    return EntityMentionIdentifier(source_id="s1", request_id="r1", entity_type="Person")


def _cluster(cluster_id="c1", confidence=0.9, similarity=0.85) -> ClusterReference:
    return ClusterReference(
        cluster_id=cluster_id, confidence_score=confidence, similarity_score=similarity
    )


def _decision(placement: ClusterReference, candidates: list[ClusterReference]) -> Decision:
    now = datetime.now(UTC)
    return Decision(
        id="hash123",
        about_entity_mention=_identifier(),
        current_placement=placement,
        candidates=candidates,
        created_at=now,
        updated_at=None,
    )


class TestIsSameOutcome:
    def test_identical_placement_and_candidates_is_same(self):
        existing = _decision(_cluster("c1"), [_cluster("c2"), _cluster("c3")])
        assert is_same_outcome(existing, _cluster("c1"), [_cluster("c2"), _cluster("c3")]) is True

    def test_empty_candidates_both_sides_is_same(self):
        existing = _decision(_cluster("c1"), [])
        assert is_same_outcome(existing, _cluster("c1"), []) is True

    def test_different_cluster_id_is_not_same(self):
        existing = _decision(_cluster("c1"), [])
        assert is_same_outcome(existing, _cluster("c2"), []) is False

    def test_same_cluster_lower_confidence_is_not_same(self):
        existing = _decision(_cluster("c1", confidence=0.9), [])
        assert is_same_outcome(existing, _cluster("c1", confidence=0.55), []) is False

    def test_same_cluster_changed_similarity_is_not_same(self):
        existing = _decision(_cluster("c1", similarity=0.85), [])
        assert is_same_outcome(existing, _cluster("c1", similarity=0.50), []) is False

    def test_changed_candidate_content_is_not_same(self):
        existing = _decision(_cluster("c1"), [_cluster("c2")])
        assert is_same_outcome(existing, _cluster("c1"), [_cluster("c2"), _cluster("c3")]) is False

    def test_changed_candidate_order_is_not_same(self):
        existing = _decision(_cluster("c1"), [_cluster("c2"), _cluster("c3")])
        assert is_same_outcome(existing, _cluster("c1"), [_cluster("c3"), _cluster("c2")]) is False
