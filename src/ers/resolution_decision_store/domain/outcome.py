"""Outcome-equality helper for the Resolution Decision Store.

An ERE *outcome* applied to a decision is the pair ``(current_placement,
candidates)``.  Comparing whole outcomes — not just cluster ids — is what lets
the store detect that a re-assessment changed something material (for example a
lower confidence on the same cluster) and must therefore write through and
advance ``updated_at`` so the decision re-surfaces for curator review.
"""
from erspec.models.core import ClusterReference, Decision


def is_same_outcome(
    existing: Decision,
    current: ClusterReference,
    candidates: list[ClusterReference],
) -> bool:
    """Return True iff the stored outcome equals the incoming one.

    The outcome is the placement plus the ordered candidate list.  ``candidates``
    must already be truncated to the persisted maximum so the comparison is made
    against what is actually stored on the decision document.

    Args:
        existing: The currently stored decision.
        current: The incoming cluster placement.
        candidates: The incoming candidate list, already truncated to the
            persisted maximum.

    Returns:
        True when ``current`` and ``candidates`` are structurally equal to the
        stored placement and candidates; False on any material difference
        (cluster id, confidence, similarity, or candidate content/order).
    """
    return bool(
        existing.current_placement == current and existing.candidates == candidates
    )
