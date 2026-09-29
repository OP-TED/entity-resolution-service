"""Port: per-cluster cardinality projection (cluster_sizes collection).

Maintained by the decision-store integration use case on placement changes;
consumed by curation read paths (sort, preview, stats) — added in later phases.
"""
from typing import Protocol


class ClusterSizeIndex(Protocol):
    """Read/write port for the per-cluster cardinality projection.

    Maintained by the decision-store integration use case on placement changes;
    consumed by curation read paths (sort, preview, stats) — added in later phases.
    """

    async def shift(
        self,
        *,
        from_cluster: str | None,
        to_cluster: str | None,
        by: int = 1,
    ) -> None:
        """Apply a cardinality delta across one or two clusters.

        Args:
            from_cluster: Cluster to decrement by ``by``.  ``None`` on the
                insert path — the decision did not belong to any cluster before.
            to_cluster: Cluster to increment by ``by``.  ``None`` on a removal
                path — the decision is being deleted with no successor cluster.
            by: Absolute value of the delta (default 1).

        Note:
            ``from_cluster == to_cluster`` is a no-op.
            Negative counts must be prevented at the adapter level.
            This call is bulk-write friendly — a single round-trip covers both
            the decrement and the increment.
        """

    async def get_size(self, cluster_id: str) -> int:
        """Return current size for the given cluster, or 0 if absent.

        Args:
            cluster_id: The cluster identifier to look up.

        Returns:
            The current cardinality as a non-negative integer, or 0 if the
            cluster is not yet tracked in the projection.
        """
