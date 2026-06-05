"""Verification script: check cluster_sizes projection is consistent with decisions.

Computes the ground-truth cluster counts from ``decisions`` and compares them
against the ``cluster_sizes`` projection.  Reports:

- Clusters in ``decisions`` but missing from ``cluster_sizes``.
- Clusters in ``cluster_sizes`` but absent from ``decisions`` (stale entries).
- Clusters present in both but with mismatched sizes.

Exit codes:
    0 — projection is fully consistent.
    1 — drift detected (see logged report).

Usage::

    poetry run python -m scripts.verify_cluster_sizes
    poetry run python -m scripts.verify_cluster_sizes --verbose
"""

import argparse
import asyncio
import logging
import sys
from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from ers import config

log = logging.getLogger(__name__)

_DECISIONS_COLLECTION = "decisions"
_CLUSTER_SIZES_COLLECTION = "cluster_sizes"
_FIELD_CLUSTER_ID = "current_placement.cluster_id"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that the cluster_sizes projection is consistent with the "
            "decisions collection.  Exits 0 if consistent, 1 if drift is found."
        )
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Log each consistent cluster as well as discrepancies.",
    )
    return parser


async def _aggregate_cluster_counts(db: AsyncDatabase[Any]) -> dict[str, int]:
    """Aggregate decisions by cluster_id and return ground-truth counts.

    Args:
        db: Connected async MongoDB database.

    Returns:
        Mapping of ``{cluster_id: count}`` from the decisions collection.
    """
    pipeline: list[dict[str, Any]] = [
        {
            "$group": {
                "_id": f"${_FIELD_CLUSTER_ID}",
                "count": {"$sum": 1},
            }
        }
    ]
    cursor = await db[_DECISIONS_COLLECTION].aggregate(pipeline)
    rows = await cursor.to_list()

    counts: dict[str, int] = {}
    for row in rows:
        cluster_id = row.get("_id")
        if not cluster_id or not isinstance(cluster_id, str):
            continue
        counts[cluster_id] = int(row["count"])
    return counts


async def _read_projection(db: AsyncDatabase[Any]) -> dict[str, int]:
    """Read all documents from cluster_sizes and return as a mapping.

    Args:
        db: Connected async MongoDB database.

    Returns:
        Mapping of ``{cluster_id: size}`` from the cluster_sizes collection.
    """
    cursor = db[_CLUSTER_SIZES_COLLECTION].find({}, projection={"size": 1})
    projection: dict[str, int] = {}
    async for doc in cursor:
        cluster_id = doc.get("_id")
        size = doc.get("size")
        if cluster_id and isinstance(size, (int, float)):
            projection[str(cluster_id)] = int(size)
    return projection


async def _verify(db: AsyncDatabase[Any], *, verbose: bool) -> bool:
    """Compare ground-truth vs projection and report discrepancies.

    Args:
        db: Connected async MongoDB database.
        verbose: When True, also log consistent clusters.

    Returns:
        True if the projection is fully consistent, False if drift is detected.
    """
    log.info("Reading ground-truth from %r …", _DECISIONS_COLLECTION)
    ground_truth = await _aggregate_cluster_counts(db)
    log.info("Reading projection from %r …", _CLUSTER_SIZES_COLLECTION)
    projection = await _read_projection(db)

    all_clusters = set(ground_truth) | set(projection)
    drifts: list[str] = []

    for cluster_id in sorted(all_clusters):
        expected = ground_truth.get(cluster_id, 0)
        actual = projection.get(cluster_id, 0)

        if expected == actual:
            if verbose:
                log.info("OK  cluster=%r  size=%d", cluster_id, expected)
        else:
            drifts.append(cluster_id)
            log.warning(
                "DRIFT  cluster=%r  decisions=%d  cluster_sizes=%d  delta=%+d",
                cluster_id,
                expected,
                actual,
                actual - expected,
            )

    if drifts:
        log.error(
            "Projection inconsistent: %d cluster(s) have drift. "
            "Run backfill_cluster_sizes to repair (upserts missing entries "
            "and deletes stale ones).",
            len(drifts),
        )
        return False

    log.info(
        "Projection consistent: %d cluster(s) verified.",
        len(all_clusters),
    )
    return True


async def main() -> None:
    """Entry point: parse arguments and run the verification."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    parser = _build_arg_parser()
    args = parser.parse_args()

    mongo_url = config.MONGO_URI
    log.info("Connecting to MongoDB at %s …", mongo_url)

    async with AsyncMongoClient(mongo_url) as client:
        db_name = config.MONGO_DATABASE_NAME
        db = client[db_name]
        log.info("Using database: %s", db_name)
        consistent = await _verify(db, verbose=args.verbose)

    sys.exit(0 if consistent else 1)


if __name__ == "__main__":
    asyncio.run(main())
