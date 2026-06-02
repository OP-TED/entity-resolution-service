"""Backfill script: set previous_review_count on each decision document.

Counts all user actions per decision_id in the ``user_actions`` collection and
writes the result to ``previous_review_count`` on the corresponding document in
the ``decisions`` collection.

This is a one-off operational utility — safe to re-run (idempotent).

Usage:
    poetry run python -m scripts.backfill_previous_review_count
    poetry run python -m scripts.backfill_previous_review_count --dry-run
    poetry run python -m scripts.backfill_previous_review_count --batch-size 500
"""

import argparse
import asyncio
import logging
from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from erspec.models.core import EntityMentionIdentifier

from ers import config
from ers.commons.adapters.provisional_id import derive_provisional_cluster_id

log = logging.getLogger(__name__)

_DECISIONS_COLLECTION = "decisions"
_USER_ACTIONS_COLLECTION = "user_actions"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill previous_review_count on all decision documents from user_actions counts."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be updated without writing to MongoDB.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        metavar="N",
        help="Number of decisions to update per bulk write batch (default: 500).",
    )
    return parser


async def _count_actions_per_decision(db: AsyncDatabase[Any]) -> dict[str, int]:
    """Aggregate user_actions by about_entity_mention and map to decision _id.

    Each ``UserAction`` document stores ``about_entity_mention`` (the entity
    mention triad).  The corresponding ``Decision._id`` is the SHA-256 hash of
    the triad, computed by ``derive_provisional_cluster_id``.  This function
    groups actions by triad, then derives the decision _id for each group.

    Returns:
        Mapping of ``{decision_id: action_count}`` for all decisions that
        have at least one recorded action.
    """
    pipeline: list[dict[str, Any]] = [
        {
            "$group": {
                "_id": "$about_entity_mention",
                "count": {"$sum": 1},
            }
        }
    ]
    cursor = await db[_USER_ACTIONS_COLLECTION].aggregate(pipeline)
    rows = await cursor.to_list()

    counts: dict[str, int] = {}
    for row in rows:
        triad_doc = row.get("_id")
        if not triad_doc or not isinstance(triad_doc, dict):
            continue
        try:
            identifier = EntityMentionIdentifier.model_validate(triad_doc)
        except Exception as exc:  # noqa: BLE001
            log.warning("Skipping malformed about_entity_mention document: %s — %s", triad_doc, exc)
            continue
        decision_id = derive_provisional_cluster_id(identifier)
        counts[decision_id] = row["count"]

    return counts


async def _build_bulk_ops(counts: dict[str, int]) -> list[dict[str, Any]]:
    """Build pymongo UpdateOne operations from the action counts.

    Args:
        counts: Mapping of decision_id to action count.

    Returns:
        List of ``{filter, update}`` dicts suitable for ``bulk_write``.
    """
    from pymongo import UpdateOne  # noqa: PLC0415 — lazy import for testability

    return [
        UpdateOne(
            filter={"_id": decision_id},
            update={"$set": {"previous_review_count": count}},
            upsert=False,
        )
        for decision_id, count in counts.items()
    ]


async def _run_backfill(
    db: AsyncDatabase[Any],
    *,
    dry_run: bool,
    batch_size: int,
) -> None:
    """Execute the backfill.

    Args:
        db: Connected AsyncDatabase instance.
        dry_run: When True, print planned writes instead of executing them.
        batch_size: Maximum operations per ``bulk_write`` call.
    """
    log.info("Counting user actions per decision …")
    counts = await _count_actions_per_decision(db)
    log.info("Found %d decisions with recorded actions.", len(counts))

    if not counts:
        log.info("Nothing to backfill — no user actions found.")
        return

    ops = await _build_bulk_ops(counts)

    if dry_run:
        for decision_id, count in counts.items():
            log.info(
                "[DRY-RUN] Would set previous_review_count=%d on decision _id=%s",
                count,
                decision_id,
            )
        log.info("[DRY-RUN] Total operations that would be issued: %d", len(ops))
        return

    total_modified = 0
    decisions = db[_DECISIONS_COLLECTION]
    for batch_start in range(0, len(ops), batch_size):
        batch = ops[batch_start : batch_start + batch_size]
        result = await decisions.bulk_write(batch, ordered=False)
        total_modified += result.modified_count
        log.info(
            "Batch %d/%d: modified %d documents.",
            batch_start // batch_size + 1,
            (len(ops) + batch_size - 1) // batch_size,
            result.modified_count,
        )

    log.info("Backfill complete. Total documents modified: %d.", total_modified)


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
