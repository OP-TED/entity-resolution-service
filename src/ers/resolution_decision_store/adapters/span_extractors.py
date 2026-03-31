"""OTel span attribute extractors for the Resolution Decision Store.

Import this module at application startup only — NOT at module level in other packages.
"""
from erspec.models.core import Decision

from ers.commons.adapters.tracing import register_span_extractor

register_span_extractor(
    Decision,
    lambda d: {
        "decision_store.source_id": d.about_entity_mention.source_id,
        "decision_store.cluster_id": d.current_placement.cluster_id,
        "decision_store.candidate_count": len(d.candidates),
    },
)
