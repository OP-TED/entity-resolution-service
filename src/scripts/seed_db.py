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

# only used for seeding/testing
from test.unit.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
    EntityMentionIdentifierFactory,
    ResolutionRequestRecordFactory,
    UserActionFactory,
)

from ers import config
from ers.curation.adapters.user_action_repository import (
    MongoUserActionCurationRepository,
)
from ers.request_registry.adapters.records_repository import (
    MongoResolutionRequestRepository,
)
from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository
from ers.users.adapters.user_repository import MongoUserRepository
from ers.users.domain.users import User
from scripts.backfill_cluster_sizes import _run_backfill as _backfill_cluster_sizes

ENTITY_TYPES = ["ORGANISATION", "PROCEDURE"]
ACTION_TYPES = list(UserActionType)

SEED_USERS = [
    {"email": "alice.curator@example.com", "is_verified": True},
    {"email": "bob.reviewer@example.com", "is_verified": True},
    {"email": "carol.admin@example.com", "is_superuser": True, "is_verified": True},
    {"email": "dave.new@example.com", "is_verified": False},
]

SEED_COLLECTIONS = ["decisions", "resolution_requests", "user_actions", "users"]


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
        record = ResolutionRequestRecordFactory.build_for_entity_type(
            entity_type,
            identifiedBy=identifier,
        )
        mentions.append(record)
        await mention_repo.store(record)
    return mentions


def _build_cluster_references(
    mentions: list[Any],
    num_clusters: int,
) -> tuple[dict[str, list[str]], dict[str, list[Any]]]:
    if not mentions:
        return {}, {}

    mentions_by_type: dict[str, list[Any]] = {}
    for mention in mentions:
        mentions_by_type.setdefault(mention.identifiedBy.entity_type, []).append(mention)

    cluster_ids_by_type: dict[str, list[str]] = {}
    cluster_refs_by_mention: dict[str, list[Any]] = {}
    cluster_counter = 0

    for etype, type_mentions in mentions_by_type.items():
        share = max(1, round(num_clusters * len(type_mentions) / len(mentions)))
        type_cluster_ids = [f"cluster-{cluster_counter + i:04d}" for i in range(share)]
        cluster_counter += share
        cluster_ids_by_type[etype] = type_cluster_ids

        shuffled = list(type_mentions)
        random.shuffle(shuffled)
        chunk_size = max(1, len(shuffled) // len(type_cluster_ids))

        for i, cluster_id in enumerate(type_cluster_ids):
            start = i * chunk_size
            end = start + chunk_size if i < len(type_cluster_ids) - 1 else len(shuffled)
            group = shuffled[start:end]
            if not group:
                break
            for mention in group:
                key = mention.identifiedBy.source_id
                cluster_refs_by_mention.setdefault(key, []).append(
                    ClusterReferenceFactory.build(cluster_id=cluster_id)
                )

    return cluster_ids_by_type, cluster_refs_by_mention


def _build_candidates(
    mention: Any,
    cluster_refs_by_mention: dict[str, list[Any]],
    cluster_ids_by_type: dict[str, list[str]],
) -> list[Any]:
    key = mention.identifiedBy.source_id
    type_cluster_ids = cluster_ids_by_type.get(mention.identifiedBy.entity_type, [])
    candidates = list(cluster_refs_by_mention.get(key, []))
    for _ in range(random.randint(0, 3)):
        if type_cluster_ids:
            candidates.append(
                ClusterReferenceFactory.build(cluster_id=random.choice(type_cluster_ids))
            )
    return candidates or [ClusterReferenceFactory.build()]


async def _create_decisions(
    mentions: list[Any],
    cluster_refs_by_mention: dict[str, list[Any]],
    cluster_ids_by_type: dict[str, list[str]],
    decision_repo: MongoDecisionRepository,
    db: Any,
) -> list[Any]:
    """Persist decisions and materialise the review-state primitives.

    The factory-built ``Decision`` model does not carry the denormalised
    review-state fields (``previous_review_count`` and ``reviewed_since_placement``)
    because the domain model forbids extra fields. After ``save`` we set them
    explicitly so seeded data matches the production shape — the curation list
    indexes and filters can only plan against documents that actually carry the
    field.
    """
    decisions: list[Any] = []
    for mention in mentions:
        candidates = _build_candidates(mention, cluster_refs_by_mention, cluster_ids_by_type)
        created_at = _random_past()
        decision = DecisionFactory.build(
            about_entity_mention=mention.identifiedBy,
            current_placement=candidates[0],
            candidates=candidates,
            created_at=created_at,
        )
        decisions.append(decision)
        await decision_repo.save(decision)
        await db["decisions"].update_one(
            {"_id": decision.id},
            {"$set": {"reviewed_since_placement": False, "previous_review_count": 0}},
        )
    return decisions


def _selected_cluster_for_action(decision: Any, action_type: UserActionType) -> Any | None:
    if action_type == UserActionType.ACCEPT_TOP:
        return decision.current_placement
    if action_type == UserActionType.ACCEPT_ALTERNATIVE and len(decision.candidates) > 1:
        return random.choice(decision.candidates[1:])
    return None


async def _create_users(user_repo: MongoUserRepository) -> list[User]:
    from ers.commons.adapters.hasher import Argon2PasswordHasher

    hasher = Argon2PasswordHasher()
    users: list[User] = []
    for spec in SEED_USERS:
        user = User(
            id=f"user-{spec['email'].split('@')[0]}",
            email=spec["email"],
            hashed_password=hasher.hash("password123"),
            is_active=True,
            is_superuser=spec.get("is_superuser", False),
            is_verified=spec.get("is_verified", False),
            created_at=_random_past(max_days=180),
        )
        await user_repo.save(user)
        users.append(user)
    return users


async def _create_user_actions(
    decisions: list[Any],
    action_repo: MongoUserActionCurationRepository,
    decision_repo: MongoDecisionRepository,
    user_ids: list[str],
) -> int:
    """Persist user actions and dogfood the production lifecycle writer.

    After saving the action we call ``decision_repo.record_review`` — the same
    code path used by ``UserActionService.record_*`` in production — so the
    seeded ``reviewed_since_placement`` reflects what real curator actions
    produce. Actions whose ``created_at`` is after the decision's placement
    boundary flip the flag to ``True`` (the typical case here, since seeded
    actions are minutes after decision creation).
    """
    curated_decisions = random.sample(decisions, k=min(len(decisions) // 3, len(decisions)))
    action_count = 0
    for decision in curated_decisions:
        action_type = random.choice(ACTION_TYPES)
        action = UserActionFactory.build(
            about_entity_mention=decision.about_entity_mention,
            candidates=decision.candidates,
            selected_cluster=_selected_cluster_for_action(decision, action_type),
            action_type=action_type,
            actor=random.choice(user_ids),
            created_at=decision.created_at + timedelta(minutes=random.randint(1, 120)),
        )
        await action_repo.save(action)
        await decision_repo.record_review(decision.id, action.created_at)
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
    decision_repo = MongoDecisionRepository(db)
    action_repo = MongoUserActionCurationRepository(db)
    user_repo = MongoUserRepository(db)

    users = await _create_users(user_repo)
    user_ids = [u.id for u in users]
    mentions = await _create_mentions(mention_repo, num_mentions, num_requests)
    cluster_ids_by_type, cluster_refs_by_mention = _build_cluster_references(mentions, num_clusters)
    decisions = await _create_decisions(
        mentions,
        cluster_refs_by_mention,
        cluster_ids_by_type,
        decision_repo,
        db,
    )
    action_count = await _create_user_actions(decisions, action_repo, decision_repo, user_ids)
    await _backfill_cluster_sizes(db, dry_run=False, batch_size=500)

    print(f"Seeded database '{config.MONGO_DATABASE_NAME}':")
    print(f"  {len(users)} users ({', '.join(u.email for u in users)})")
    print(
        f"  {num_mentions} entity mentions ({num_requests} requests, {len(ENTITY_TYPES)} entity types)"
    )
    total_clusters = sum(len(ids) for ids in cluster_ids_by_type.values())
    cluster_summary = ", ".join(f"{k}: {len(v)}" for k, v in cluster_ids_by_type.items())
    print(f"  {total_clusters} clusters ({cluster_summary})")
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
