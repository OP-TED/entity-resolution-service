from datetime import datetime, timedelta, timezone

import pytest
from pymongo.asynchronous.database import AsyncDatabase

from ers.commons.adapters import MongoCollections
from ers.curation.adapters.user_action_repository import (
    MongoUserActionCurationRepository,
)
from tests.factories import EntityMentionIdentifierFactory, UserActionFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(mongo_db: AsyncDatabase) -> MongoUserActionCurationRepository:
    return MongoUserActionCurationRepository(MongoCollections(mongo_db).user_actions)


class TestSaveAndFindById:
    async def test_save_and_retrieve(
        self, repo: MongoUserActionCurationRepository
    ) -> None:
        action = UserActionFactory.build()
        await repo.save(action)

        found = await repo.find_by_id(action.id)

        assert found is not None
        assert found.id == action.id
        assert found.action_type == action.action_type

    async def test_find_by_id_not_found(
        self, repo: MongoUserActionCurationRepository
    ) -> None:
        result = await repo.find_by_id("nonexistent")
        assert result is None


class TestHasCurrentAction:
    async def test_returns_true_when_action_exists_since(
        self, repo: MongoUserActionCurationRepository
    ) -> None:
        action = UserActionFactory.build(created_at=datetime.now(timezone.utc))
        await repo.save(action)

        result = await repo.has_current_action(
            about_entity_mention=action.about_entity_mention,
            since=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        assert result is True

    async def test_returns_false_when_no_action_since(
        self, repo: MongoUserActionCurationRepository
    ) -> None:
        action = UserActionFactory.build(
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        await repo.save(action)

        result = await repo.has_current_action(
            about_entity_mention=action.about_entity_mention,
            since=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        assert result is False

    async def test_returns_false_for_different_entity(
        self, repo: MongoUserActionCurationRepository
    ) -> None:
        action = UserActionFactory.build(created_at=datetime.now(timezone.utc))
        await repo.save(action)

        other_mention = EntityMentionIdentifierFactory.build()
        result = await repo.has_current_action(
            about_entity_mention=other_mention,
            since=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        assert result is False
