"""Smoke tests for Resolution Decision Store span extractor registration."""
from datetime import UTC

from erspec.models.core import Decision

import ers.resolution_decision_store.adapters.span_extractors  # noqa: F401 — registers extractors
from ers.commons.adapters.tracing import _extractors


def test_decision_extractor_is_registered():
    assert Decision in _extractors


def test_decision_extractor_returns_expected_attributes():
    from datetime import datetime

    from erspec.models.core import ClusterReference, EntityMentionIdentifier

    decision = Decision(
        id="hash123",
        about_entity_mention=EntityMentionIdentifier(
            source_id="s1", request_id="r1", entity_type="Person"
        ),
        current_placement=ClusterReference(
            cluster_id="c1", confidence_score=0.9, similarity_score=0.85
        ),
        candidates=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    extractor = _extractors[Decision]
    attrs = extractor(decision)
    assert attrs["decision_store.source_id"] == "s1"
    assert attrs["decision_store.cluster_id"] == "c1"
    assert attrs["decision_store.candidate_count"] == 0
