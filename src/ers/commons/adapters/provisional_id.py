"""Deterministic provisional cluster ID derivation from entity mention triads.

The provisional cluster ID is the SHA-256 hex digest of the concatenation of the
three identifying fields. It serves dual purpose:
- As ``Decision.id`` (set via ``$setOnInsert`` on first write — never changes)
- As the provisional ``cluster_id`` when ERE does not respond in time
"""
from erspec.models.core import EntityMentionIdentifier

from ers.commons.adapters.hasher import SHA256ContentHasher

_hasher = SHA256ContentHasher()


def derive_provisional_cluster_id(identifier: EntityMentionIdentifier) -> str:
    """Return a deterministic 64-char SHA-256 hex digest for the entity mention triad.

    Args:
        identifier: The EntityMentionIdentifier containing the correlation triad.

    Returns:
        A 64-character lowercase hex string. Identical input always produces
        identical output.
    """
    content = f"{identifier.source_id}{identifier.request_id}{identifier.entity_type}"
    return _hasher.hash(content)
