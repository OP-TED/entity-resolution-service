from datetime import datetime, timezone

import pytest
from erspec.models.core import UserActionType
from pymongo.asynchronous.database import AsyncDatabase

from ers.adapters.mongodb import MongoCollections, MongoStatisticsRepository
from ers.application.dtos import StatisticsFilters
from tests.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
    EntityMentionFactory,
    UserActionFactory,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(mongo_db: AsyncDatabase) -> MongoStatisticsRepository:
    return MongoStatisticsRepository(mongo_db)


async def _seed_data(db: AsyncDatabase) -> None:
    """Insert a realistic dataset across all collections."""
    from ers.adapters.mongodb import (
        MongoDecisionRepository,
        MongoEntityMentionRepository,
        MongoUserActionRepository,
    )

    collections = MongoCollections(db)
    mention_repo = MongoEntityMentionRepository(collections.entity_mentions)
    decision_repo = MongoDecisionRepository(collections.decisions)
    action_repo = MongoUserActionRepository(collections.user_actions)

    mentions = EntityMentionFactory.batch(4)
    mentions[0].identifiedBy.entity_type = "ORGANISATION"
    mentions[1].identifiedBy.entity_type = "ORGANISATION"
    mentions[2].identifiedBy.entity_type = "PROCEDURE"
    mentions[3].identifiedBy.entity_type = "ORGANISATION"
    for m in mentions:
        await mention_repo.save(m)

    cluster_a = ClusterReferenceFactory.build(cluster_id="cluster-a")
    cluster_b = ClusterReferenceFactory.build(cluster_id="cluster-b")

    decisions = [
        DecisionFactory.build(
            about_entity_mention=mentions[0].identifiedBy,
            current_placement=cluster_a,
        ),
        DecisionFactory.build(
            about_entity_mention=mentions[1].identifiedBy,
            current_placement=cluster_a,
        ),
        DecisionFactory.build(
            about_entity_mention=mentions[2].identifiedBy,
            current_placement=cluster_b,
        ),
    ]
    for d in decisions:
        await decision_repo.save(d)

    actions = [
        UserActionFactory.build(
            about_entity_mention=mentions[0].identifiedBy,
            action_type=UserActionType.ACCEPT_TOP,
            created_at=datetime.now(timezone.utc),
        ),
        UserActionFactory.build(
            about_entity_mention=mentions[1].identifiedBy,
            action_type=UserActionType.ACCEPT_ALTERNATIVE,
            created_at=datetime.now(timezone.utc),
        ),
        UserActionFactory.build(
            about_entity_mention=mentions[2].identifiedBy,
            action_type=UserActionType.REJECT_ALL,
            created_at=datetime.now(timezone.utc),
        ),
    ]
    for a in actions:
        await action_repo.save(a)


class TestGetCurationStatistics:
    async def test_counts_action_types(
        self, repo: MongoStatisticsRepository, mongo_db: AsyncDatabase
    ) -> None:
        await _seed_data(mongo_db)

        stats = await repo.get_curation_statistics(StatisticsFilters())

        assert stats.total_decisions == 3
        assert stats.selected_top == 1
        assert stats.selected_alternative == 1
        assert stats.rejected_all == 1

    async def test_empty_database(self, repo: MongoStatisticsRepository) -> None:
        stats = await repo.get_curation_statistics(StatisticsFilters())

        assert stats.total_decisions == 0
        assert stats.selected_top == 0
        assert stats.selected_alternative == 0
        assert stats.rejected_all == 0


class TestGetRegistryStatistics:
    async def test_counts_entities(
        self, repo: MongoStatisticsRepository, mongo_db: AsyncDatabase
    ) -> None:
        await _seed_data(mongo_db)

        stats = await repo.get_registry_statistics(StatisticsFilters())

        assert stats.total_entity_mentions == 4
        assert stats.total_canonical_entities == 2
        assert stats.average_cluster_size == 1.5
        assert stats.resolution_requests > 0

    async def test_empty_database(self, repo: MongoStatisticsRepository) -> None:
        stats = await repo.get_registry_statistics(StatisticsFilters())

        assert stats.total_entity_mentions == 0
        assert stats.total_canonical_entities == 0
        assert stats.average_cluster_size == 0.0
        assert stats.resolution_requests == 0
