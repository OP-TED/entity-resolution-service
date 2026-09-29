"""Backfill script: (re)build the cluster_sizes projection from decisions.

Aggregates ``decisions`` by ``current_placement.cluster_id``, then upserts each
resulting count into ``cluster_sizes`` and removes any stale entries.
The script is idempotent -- running it multiple times produces the same result.
Use it after a data migration, after the initial deployment of the cluster-size
feature, or whenever manual verification indicates drift.

Warning:
    This script uses ``$set`` (absolute overwrite) to write each cluster's count.
    Running it while decisions are actively being integrated can cause a
    ``$inc`` write from ``DecisionStoreService.store_decision`` to be lost if it
    races with the ``$set``. Run during a maintenance window or at a time when
    ERE is not actively delivering outcomes.

Usage::

    poetry run python -m scripts.backfill_cluster_sizes
    poetry run python -m scripts.backfill_cluster_sizes --dry-run
    poetry run python -m scripts.backfill_cluster_sizes --batch-size 500
"""

import argparse
import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from pymongo import AsyncMongoClient, UpdateOne
from pymongo.asynchronous.database import AsyncDatabase

from ers import config

log = logging.getLogger(__name__)

_DECISIONS_COLLECTION = "decisions"
_CLUSTER_SIZES_COLLECTION = "cluster_sizes"
_FIELD_CLUSTER_ID = "current_placement.cluster_id"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill cluster_sizes projection from decisions collection. "
            "Idempotent — safe to re-run."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be written without modifying MongoDB.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        metavar="N",
        help=(
            "Number of write operations per bulk_write call (default: 500). "
            "Controls write-batch size only; the full aggregation result is "
            "loaded into memory before writes begin."
        ),
    )
    return parser


async def _aggregate_cluster_counts(db: AsyncDatabase[Any]) -> dict[str, int]:
    """Aggregate decisions by cluster_id and return counts.

    Args:
        db: Connected async MongoDB database.

    Returns:
        Mapping of ``{cluster_id: count}`` for all clusters present in decisions.
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
            log.warning("Skipping row with unexpected cluster_id: %r", cluster_id)
            continue
        counts[cluster_id] = int(row["count"])

    return counts


async def _delete_stale_entries(
    db: AsyncDatabase[Any],
    *,
    live_cluster_ids: set[str],
    dry_run: bool,
) -> int:
    """Delete cluster_sizes documents whose cluster_id is no longer in decisions.

    Args:
        db: Connected async MongoDB database.
        live_cluster_ids: Set of cluster IDs currently present in decisions.
        dry_run: When True, log what would be deleted without executing.

    Returns:
        Number of documents deleted (or that would be deleted in dry-run mode).
    """
    stale_filter: dict[str, Any] = {"_id": {"$nin": sorted(live_cluster_ids)}}
    collection = db[_CLUSTER_SIZES_COLLECTION]

    if dry_run:
        stale_count = await collection.count_documents(stale_filter)
        log.info("[DRY-RUN] Stale entries that would be deleted: %d", stale_count)
        return stale_count

    result = await collection.delete_many(stale_filter)
    if result.deleted_count:
        log.info("Deleted %d stale cluster_sizes entries.", result.deleted_count)
    return result.deleted_count


def _build_upsert_ops(counts: dict[str, int]) -> list[UpdateOne]:
    """Build UpdateOne upsert operations for each cluster.

    Uses ``$set`` so existing documents are fully overwritten with the
    recomputed size.  ``$setOnInsert`` seeds the ``_id`` for new documents.

    Args:
        counts: Mapping of ``{cluster_id: count}``.

    Returns:
        List of ``UpdateOne`` operations ready for ``bulk_write``.
    """
    now = datetime.now(UTC)
    return [
        UpdateOne(
            filter={"_id": cluster_id},
            update={
                "$set": {"size": count, "updated_at": now},
                "$setOnInsert": {"_id": cluster_id},
            },
            upsert=True,
        )
        for cluster_id, count in counts.items()
    ]


async def _run_backfill(
    db: AsyncDatabase[Any],
    *,
    dry_run: bool,
    batch_size: int,
) -> None:
    """Execute the backfill.

    Args:
        db: Connected async MongoDB database.
        dry_run: When True, log planned writes instead of executing them.
        batch_size: Maximum operations per ``bulk_write`` call.
    """
    log.info("Aggregating cluster sizes from %s …", _DECISIONS_COLLECTION)
    counts = await _aggregate_cluster_counts(db)
    log.info("Found %d distinct clusters.", len(counts))

    if not counts:
        log.info("Nothing to backfill — no clusters found.")
        return

    ops = _build_upsert_ops(counts)

    live_cluster_ids = set(counts.keys())

    if dry_run:
        for cluster_id, count in sorted(counts.items()):
            log.info("[DRY-RUN] Would upsert cluster_sizes[%r] = %d", cluster_id, count)
        log.info("[DRY-RUN] Total operations that would be issued: %d", len(ops))
        await _delete_stale_entries(db, live_cluster_ids=live_cluster_ids, dry_run=True)
        return

    total_upserted = 0
    total_modified = 0
    collection = db[_CLUSTER_SIZES_COLLECTION]
    num_batches = (len(ops) + batch_size - 1) // batch_size

    for batch_num, batch_start in enumerate(range(0, len(ops), batch_size), start=1):
        batch = ops[batch_start : batch_start + batch_size]
        result = await collection.bulk_write(batch, ordered=False)
        total_upserted += result.upserted_count
        total_modified += result.modified_count
        log.info(
            "Batch %d/%d: upserted=%d, modified=%d.",
            batch_num,
            num_batches,
            result.upserted_count,
            result.modified_count,
        )

    log.info(
        "Backfill complete. Clusters processed: %d. Upserted: %d. Modified: %d.",
        len(counts),
        total_upserted,
        total_modified,
    )

    await _delete_stale_entries(db, live_cluster_ids=live_cluster_ids, dry_run=False)


async def main() -> None:
    """Entry point: parse arguments and run the backfill."""
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
        await _run_backfill(db, dry_run=args.dry_run, batch_size=args.batch_size)


if __name__ == "__main__":
    asyncio.run(main())
