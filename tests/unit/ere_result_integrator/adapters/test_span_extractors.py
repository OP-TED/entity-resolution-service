"""Smoke tests for ERE Result Integrator span extractor registration."""
from datetime import UTC, datetime

from erspec.models.core import ClusterReference, EntityMentionIdentifier
from erspec.models.ere import EntityMentionResolutionResponse

import ers.ere_result_integrator.adapters.span_extractors  # noqa: F401 — registers extractors
from ers.commons.adapters.tracing import _extractors


def test_response_extractor_is_registered():
    assert EntityMentionResolutionResponse in _extractors


def test_response_extractor_returns_expected_attributes():
    identifier = EntityMentionIdentifier(
        source_id="SYS_A", request_id="req-001", entity_type="Organization"
    )
    response = EntityMentionResolutionResponse(
        ere_request_id="req-001:001",
        entity_mention_id=identifier,
        candidates=[
            ClusterReference(cluster_id="c1", confidence_score=0.9, similarity_score=0.85),
            ClusterReference(cluster_id="c2", confidence_score=0.5, similarity_score=0.45),
        ],
        timestamp=datetime.now(UTC),
    )
    extractor = _extractors[EntityMentionResolutionResponse]
    attrs = extractor(response)
    assert attrs["ere_result_integrator.source_id"] == "SYS_A"
    assert attrs["ere_result_integrator.entity_type"] == "Organization"
    assert attrs["ere_result_integrator.ere_request_id"] == "req-001:001"
    assert attrs["ere_result_integrator.candidate_count"] == 2
