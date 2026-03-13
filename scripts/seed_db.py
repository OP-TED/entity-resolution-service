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
from datetime import datetime, timedelta, timezone

from erspec.models.core import UserActionType
from pymongo import AsyncMongoClient

from ers.adapters.mongodb import (
    MongoCollections,
    MongoDecisionRepository,
    MongoEntityMentionRepository,
    MongoUserActionRepository,
)
from ers.config import get_settings

# only used for seeding/testing
from tests.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
    EntityMentionFactory,
    EntityMentionIdentifierFactory,
    UserActionFactory,
)

ENTITY_TYPES = ["ORGANISATION", "PROCEDURE"]
ACTION_TYPES = list(UserActionType)
CURATORS = ["curator-1", "curator-2", "curator-3"]


def _random_past(max_days: int = 90) -> datetime:
    return datetime.now(timezone.utc) - timedelta(
        days=random.randint(0, max_days),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )


async def seed(
    num_mentions: int = 100,
    num_clusters: int = 30,
    num_requests: int = 8,
) -> None:
    settings = get_settings()
    client = AsyncMongoClient(settings.mongo_uri)
    db = client[settings.mongo_database_name]
    collections = MongoCollections(db)

    for name in (
        MongoCollections.DECISIONS,
        MongoCollections.ENTITY_MENTIONS,
        MongoCollections.USER_ACTIONS,
    ):
        await db[name].drop()

    mention_repo = MongoEntityMentionRepository(collections.entity_mentions)
    decision_repo = MongoDecisionRepository(collections.decisions)
    action_repo = MongoUserActionRepository(collections.user_actions)

    # generate entity mentions across requests
    request_ids = [f"req-{i:04d}" for i in range(1, num_requests + 1)]
    mentions = []
    for i in range(num_mentions):
        entity_type = random.choice(ENTITY_TYPES)
        identifier = EntityMentionIdentifierFactory.build(
            source_id=f"src-{i:04d}",
            request_id=random.choice(request_ids),
            entity_type=entity_type,
        )
        mention = EntityMentionFactory.build(identifiedBy=identifier)
        mentions.append(mention)
        await mention_repo.save(mention)

    # group mentions into clusters and build cluster references
    shuffled = list(mentions)
    random.shuffle(shuffled)
    cluster_ids: list[str] = [f"cluster-{i:04d}" for i in range(num_clusters)]
    cluster_refs_by_mention: dict[str, list] = {}
    chunk_size = max(1, len(shuffled) // num_clusters)
    for i, cluster_id in enumerate(cluster_ids):
        start = i * chunk_size
        end = start + chunk_size if i < num_clusters - 1 else len(shuffled)
        group = shuffled[start:end]
        if not group:
            break
        for m in group:
            key = m.identifiedBy.source_id
            cluster_refs_by_mention.setdefault(key, []).append(
                ClusterReferenceFactory.build(cluster_id=cluster_id)
            )

    # Create one decision per mention, referencing real clusters
    decisions = []
    for mention in mentions:
        key = mention.identifiedBy.source_id
        candidates = cluster_refs_by_mention.get(key, [])
        # Add a few random alternative clusters as candidates
        extra = random.randint(0, 3)
        for _ in range(extra):
            random_cluster_id = random.choice(cluster_ids)
            candidates.append(
                ClusterReferenceFactory.build(cluster_id=random_cluster_id)
            )
        if not candidates:
            candidates = [ClusterReferenceFactory.build()]

        current = candidates[0]
        created_at = _random_past()
        decision = DecisionFactory.build(
            about_entity_mention=mention.identifiedBy,
            current_placement=current,
            candidates=candidates,
            created_at=created_at,
        )
        decisions.append(decision)
        await decision_repo.save(decision)

    # Create user actions for a subset of decisions (simulating curation)
    curated_decisions = random.sample(
        decisions, k=min(len(decisions) // 3, len(decisions))
    )
    action_count = 0
    for decision in curated_decisions:
        action_type = random.choice(ACTION_TYPES)
        selected = None
        if action_type == UserActionType.ACCEPT_TOP:
            selected = decision.current_placement
        elif (
            action_type == UserActionType.ACCEPT_ALTERNATIVE
            and len(decision.candidates) > 1
        ):
            selected = random.choice(decision.candidates[1:])
        # REJECT_ALL leaves selected as None

        action = UserActionFactory.build(
            about_entity_mention=decision.about_entity_mention,
            candidates=decision.candidates,
            selected_cluster=selected,
            action_type=action_type,
            actor=random.choice(CURATORS),
            created_at=decision.created_at + timedelta(minutes=random.randint(1, 120)),
        )
        await action_repo.save(action)
        action_count += 1

    print(f"Seeded database '{settings.mongo_database_name}':")
    print(
        f"  {num_mentions} entity mentions ({num_requests} requests, {len(ENTITY_TYPES)} entity types)"
    )
    print(f"  {num_clusters} clusters (derived from decisions)")
    print(f"  {len(decisions)} decisions")
    print(f"  {action_count} user actions")

    await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the ERS database with sample data"
    )
    parser.add_argument(
        "--mentions", type=int, default=100, help="Number of entity mentions"
    )
    parser.add_argument(
        "--clusters", type=int, default=30, help="Number of canonical entity clusters"
    )
    parser.add_argument(
        "--requests", type=int, default=8, help="Number of resolution requests"
    )
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
