"""Seed script to populate FerretDB with sample data for manual testing.

Warning:
    This will drop existing data.

Usage:
    poetry run python -m scripts.seed_db
    poetry run python -m scripts.seed_db --mentions 200 --clusters 50 --requests 10
"""

import argparse
import asyncio
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from erspec.models.core import UserActionType
from pymongo import AsyncMongoClient

from ers import config
from ers.curation.adapters.decision_repository import MongoDecisionCurationRepository
from ers.curation.adapters.user_action_repository import (
    MongoUserActionCurationRepository,
)
from ers.request_registry.adapters.records_repository import (
    MongoResolutionRequestRepository,
)

# only used for seeding/testing
from tests.unit.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
    EntityMentionIdentifierFactory,
    ResolutionRequestRecordFactory,
    UserActionFactory,
)

ENTITY_TYPES = ["ORGANISATION", "PROCEDURE"]
ACTION_TYPES = list(UserActionType)
CURATORS = ["curator-1", "curator-2", "curator-3"]

SEED_COLLECTIONS = ["decisions", "resolution_requests", "user_actions"]


def _random_past(max_days: int = 90) -> datetime:
    return datetime.now(UTC) - timedelta(
        days=random.randint(0, max_days),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )


async def _drop_seed_collections(db: Any) -> None:
    for name in SEED_COLLECTIONS:
        await db[name].drop()


async def _create_mentions(
    mention_repo: MongoResolutionRequestRepository,
    num_mentions: int,
    num_requests: int,
) -> list[Any]:
    request_ids = [f"req-{i:04d}" for i in range(1, num_requests + 1)]
    mentions: list[Any] = []
    for i in range(num_mentions):
        entity_type = random.choice(ENTITY_TYPES)
        identifier = EntityMentionIdentifierFactory.build(
            source_id=f"src-{i:04d}",
            request_id=random.choice(request_ids),
            entity_type=entity_type,
        )
        record = ResolutionRequestRecordFactory.build(identifiedBy=identifier)
        mentions.append(record)
        await mention_repo.store(record)
    return mentions


def _build_cluster_references(
    mentions: list[Any],
    num_clusters: int,
) -> tuple[list[str], dict[str, list[Any]]]:
    shuffled = list(mentions)
    random.shuffle(shuffled)
    cluster_ids = [f"cluster-{i:04d}" for i in range(num_clusters)]
    cluster_refs_by_mention: dict[str, list[Any]] = {}
    chunk_size = max(1, len(shuffled) // num_clusters)

    for i, cluster_id in enumerate(cluster_ids):
        start = i * chunk_size
        end = start + chunk_size if i < num_clusters - 1 else len(shuffled)
        group = shuffled[start:end]
        if not group:
            break
        for mention in group:
            key = mention.identifiedBy.source_id
            cluster_refs_by_mention.setdefault(key, []).append(
                ClusterReferenceFactory.build(cluster_id=cluster_id)
            )

    return cluster_ids, cluster_refs_by_mention


def _build_candidates(
    mention: Any,
    cluster_refs_by_mention: dict[str, list[Any]],
    cluster_ids: list[str],
) -> list[Any]:
    key = mention.identifiedBy.source_id
    candidates = list(cluster_refs_by_mention.get(key, []))
    for _ in range(random.randint(0, 3)):
        candidates.append(ClusterReferenceFactory.build(cluster_id=random.choice(cluster_ids)))
    return candidates or [ClusterReferenceFactory.build()]


async def _create_decisions(
    mentions: list[Any],
    cluster_refs_by_mention: dict[str, list[Any]],
    cluster_ids: list[str],
    decision_repo: MongoDecisionCurationRepository,
) -> list[Any]:
    decisions: list[Any] = []
    for mention in mentions:
        candidates = _build_candidates(mention, cluster_refs_by_mention, cluster_ids)
        created_at = _random_past()
        decision = DecisionFactory.build(
            about_entity_mention=mention.identifiedBy,
            current_placement=candidates[0],
            candidates=candidates,
            created_at=created_at,
        )
        decisions.append(decision)
        await decision_repo.save(decision)
    return decisions


def _selected_cluster_for_action(decision: Any, action_type: UserActionType) -> Any | None:
    if action_type == UserActionType.ACCEPT_TOP:
        return decision.current_placement
    if action_type == UserActionType.ACCEPT_ALTERNATIVE and len(decision.candidates) > 1:
        return random.choice(decision.candidates[1:])
    return None


async def _create_user_actions(
    decisions: list[Any],
    action_repo: MongoUserActionCurationRepository,
) -> int:
    curated_decisions = random.sample(decisions, k=min(len(decisions) // 3, len(decisions)))
    action_count = 0
    for decision in curated_decisions:
        action_type = random.choice(ACTION_TYPES)
        action = UserActionFactory.build(
            about_entity_mention=decision.about_entity_mention,
            candidates=decision.candidates,
            selected_cluster=_selected_cluster_for_action(decision, action_type),
            action_type=action_type,
            actor=random.choice(CURATORS),
            created_at=decision.created_at + timedelta(minutes=random.randint(1, 120)),
        )
        await action_repo.save(action)
        action_count += 1
    return action_count


async def seed(
    num_mentions: int = 100,
    num_clusters: int = 30,
    num_requests: int = 8,
) -> None:
    client = AsyncMongoClient(config.MONGO_URI)
    db = client[config.MONGO_DATABASE_NAME]
    await _drop_seed_collections(db)

    mention_repo = MongoResolutionRequestRepository(db)
    decision_repo = MongoDecisionCurationRepository(db)
    action_repo = MongoUserActionCurationRepository(db)

    mentions = await _create_mentions(mention_repo, num_mentions, num_requests)
    cluster_ids, cluster_refs_by_mention = _build_cluster_references(mentions, num_clusters)
    decisions = await _create_decisions(
        mentions,
        cluster_refs_by_mention,
        cluster_ids,
        decision_repo,
    )
    action_count = await _create_user_actions(decisions, action_repo)

    print(f"Seeded database '{config.MONGO_DATABASE_NAME}':")
    print(
        f"  {num_mentions} entity mentions ({num_requests} requests, {len(ENTITY_TYPES)} entity types)"
    )
    print(f"  {num_clusters} clusters (derived from decisions)")
    print(f"  {len(decisions)} decisions")
    print(f"  {action_count} user actions")

    await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the ERS database with sample data")
    parser.add_argument("--mentions", type=int, default=100, help="Number of entity mentions")
    parser.add_argument(
        "--clusters", type=int, default=30, help="Number of canonical entity clusters"
    )
    parser.add_argument("--requests", type=int, default=8, help="Number of resolution requests")
    args = parser.parse_args()
    asyncio.run(
        seed(
            num_mentions=args.mentions,
            num_clusters=args.clusters,
            num_requests=args.requests,
        )
    )


if __name__ == "__main__":
    main()
