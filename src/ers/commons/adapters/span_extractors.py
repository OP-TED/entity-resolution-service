"""Span attribute extractors for shared erspec domain types.

Import this module at application startup (app factory or test fixture) to
register EntityMention and EntityMentionIdentifier extractors with the tracing
registry. Never imported at module level from production code — registration
happens explicitly at startup.
"""

from erspec.models.core import EntityMention, EntityMentionIdentifier

from ers.commons.adapters.tracing import register_span_extractor

register_span_extractor(
    EntityMention,
    lambda m: {
        "entity_mention.source_id":      m.identifiedBy.source_id,
        "entity_mention.request_id":     str(m.identifiedBy.request_id),
        "entity_mention.entity_type":    str(m.identifiedBy.entity_type),
        "entity_mention.content_length": len(m.content.encode("utf-8")),
        # Never: m.content, m.content_type — PII/size risk
    },
)

register_span_extractor(
    EntityMentionIdentifier,
    lambda i: {
        "entity_mention.source_id":   i.source_id,
        "entity_mention.request_id":  str(i.request_id),
        "entity_mention.entity_type": str(i.entity_type),
    },
)
