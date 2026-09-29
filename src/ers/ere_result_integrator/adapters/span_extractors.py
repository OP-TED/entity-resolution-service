"""OTel span attribute extractors for the ERE Result Integrator.

Import this module at application startup only - NOT at module level in other packages.
"""
from erspec.models.ere import EntityMentionResolutionResponse

from ers.commons.adapters.tracing import register_span_extractor

register_span_extractor(
    EntityMentionResolutionResponse,
    lambda r: {
        "ere_result_integrator.source_id": r.entity_mention_id.source_id,
        "ere_result_integrator.entity_type": r.entity_mention_id.entity_type,
        "ere_result_integrator.ere_request_id": r.ere_request_id,
        "ere_result_integrator.candidate_count": len(r.candidates),
    },
)
