"""Span attribute extractors for the request_registry sub-module.

Import this module at application startup (app factory or test fixture) to
register extractors with the tracing registry.
"""

from ers.commons.adapters.tracing import register_span_extractor
from ers.request_registry.domain.records import ResolutionRequestRecord

register_span_extractor(
    ResolutionRequestRecord,
    lambda r: {
        "request_registry.request_id": str(r.identifiedBy.request_id),
        "request_registry.source_id": r.identifiedBy.source_id,
        "request_registry.entity_type": str(r.identifiedBy.entity_type),
        # content_hash is safe (not PII), useful for idempotency tracing
        "request_registry.content_hash": r.content_hash[:16],  # prefix only
    },
)
