"""Span attribute extractors for the ere_contract_client sub-module.

Import this module at application startup (app factory or test fixture) to
register extractors with the tracing registry. Never imported at module level
from production code — registration happens explicitly at startup.
"""

from erspec.models.ere import EntityMentionResolutionRequest

from ers.commons.adapters.tracing import register_span_extractor

register_span_extractor(
    EntityMentionResolutionRequest,
    lambda r: {
        "ere.ere_request_id": r.ere_request_id or "",
        **({
            "ere.source_id":   r.entity_mention.identifiedBy.source_id,
            "ere.request_id":  str(r.entity_mention.identifiedBy.request_id),
            "ere.entity_type": str(r.entity_mention.identifiedBy.entity_type),
        } if r.entity_mention else {}),
    },
)
