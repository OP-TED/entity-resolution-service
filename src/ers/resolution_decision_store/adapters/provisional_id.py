"""Backward-compatible re-export.

The canonical location is now ``ers.commons.adapters.provisional_id``.
This module re-exports for existing callers within the decision store package.
"""
from ers.commons.adapters.provisional_id import derive_provisional_cluster_id

__all__ = ["derive_provisional_cluster_id"]
