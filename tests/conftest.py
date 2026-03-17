import pytest
from erspec.models.core import ClusterReference, Decision

from tests.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
)


@pytest.fixture
def cluster_reference() -> ClusterReference:
    return ClusterReferenceFactory.build()


@pytest.fixture
def decision() -> Decision:
    return DecisionFactory.build()


@pytest.fixture
def decision_with_candidates() -> Decision:
    candidates = [
        ClusterReferenceFactory.build(confidence_score=0.9, similarity_score=0.85),
        ClusterReferenceFactory.build(confidence_score=0.7, similarity_score=0.65),
        ClusterReferenceFactory.build(confidence_score=0.5, similarity_score=0.45),
    ]
    return DecisionFactory.build(
        current_placement=candidates[0],
        candidates=candidates,
    )
