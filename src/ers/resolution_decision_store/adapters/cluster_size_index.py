"""MongoDB adapter for the ClusterSizeIndex port.

Collection layout:
    cluster_sizes
    { _id: <cluster_id>, size: <int>, updated_at: <datetime> }

Indexes:
    _id (PK by default)
    size (secondary, for cluster-size sort and stats queries in later phases)
"""
import logging
from datetime import UTC, datetime

from pymongo import UpdateOne
from pymongo.asynchronous.database import AsyncDatabase

_log = logging.getLogger(__name__)

_COLLECTION = "cluster_sizes"
_FIELD_SIZE = "size"
_FIELD_UPDATED_AT = "updated_at"


class MongoClusterSizeIndex:
    """MongoDB implementation of the ClusterSizeIndex port.

    Uses atomic ``$inc`` upserts so the increment and decrement for a
    placement change are issued as a single ``bulk_write`` round-trip.

    Args:
        db: Connected async MongoDB database instance.
    """

    def __init__(self, db: AsyncDatabase) -> None:
        self._collection = db[_COLLECTION]

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
                insert path — the decision had no prior cluster.
            to_cluster: Cluster to increment by ``by``.  ``None`` on a
                removal path — the decision is being dropped with no successor.
            by: Absolute value of the delta (default 1).  Must be positive.

        Note:
            ``from_cluster == to_cluster`` is a no-op — no database call is made.
            When both are ``None`` the call is also a no-op.
            The decrement never upserts: a non-existent ``from_cluster`` stays
            absent. After the decrement, an entry that reaches ``size <= 0`` is
            deleted (delete-on-zero), which doubles as the decrement-below-zero
            guard — no negative count is ever persisted and stats never observe a
            ``size: 0`` row.
        """
        if from_cluster is not None and from_cluster == to_cluster:
            return

        now = datetime.now(UTC)
        ops: list[UpdateOne] = []

        if from_cluster is not None:
            ops.append(
                UpdateOne(
                    {"_id": from_cluster},
                    {
                        "$inc": {_FIELD_SIZE: -by},
                        "$set": {_FIELD_UPDATED_AT: now},
                    },
                    upsert=False,
                )
            )

        if to_cluster is not None:
            ops.append(
                UpdateOne(
                    {"_id": to_cluster},
                    {
                        "$inc": {_FIELD_SIZE: by},
                        "$set": {_FIELD_UPDATED_AT: now},
                        "$setOnInsert": {"_id": to_cluster},
                    },
                    upsert=True,
                )
            )

        if not ops:
            return

        await self._collection.bulk_write(ops, ordered=False)

        if from_cluster is not None:
            # delete-on-zero + decrement-below-zero guard: drop the entry once it
            # reaches (or passes) zero so no negative count persists and stats
            # never observe a ``size: 0`` row.
            await self._collection.delete_one(
                {"_id": from_cluster, _FIELD_SIZE: {"$lte": 0}}
            )

    async def get_size(self, cluster_id: str) -> int:
        """Return current size for the given cluster, or 0 if absent.

        Args:
            cluster_id: The cluster identifier to look up.

        Returns:
            The current cardinality as a non-negative integer, or 0 if the
            cluster is not yet tracked in the projection.
        """
        doc = await self._collection.find_one(
            {"_id": cluster_id},
            projection={_FIELD_SIZE: 1},
        )
        if doc is None:
            return 0
        return int(doc[_FIELD_SIZE])

    async def ensure_indexes(self) -> None:
        """Create required MongoDB indexes for the cluster_sizes collection.

        Idempotent — safe to call on every startup.  Creates:

        - ``idx_cluster_sizes_size``: ``{size: 1}`` — supports cluster-size
          sort (§1) and stats queries (§5/§8) in later phases.
        """
        import pymongo
        await self._collection.create_index(
            [(_FIELD_SIZE, pymongo.ASCENDING)],
            name="idx_cluster_sizes_size",
            background=True,
        )
