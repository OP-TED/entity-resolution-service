from unittest.mock import MagicMock, create_autospec

import pytest

from ers.application.exceptions import NotFoundError
from ers.application.ports.entity_mention_repository import EntityMentionRepository
from ers.application.services.entity_service import EntityService
from tests.factories import EntityMentionFactory, EntityMentionIdentifierFactory


@pytest.fixture
def entity_mention_repository() -> MagicMock:
    return create_autospec(EntityMentionRepository, instance=True)


@pytest.fixture
def service(entity_mention_repository: MagicMock) -> EntityService:
    return EntityService(entity_mention_repository=entity_mention_repository)


class TestGetEntityMention:
    async def test_returns_entity_mention(
        self,
        service: EntityService,
        entity_mention_repository: MagicMock,
    ) -> None:
        entity_mention = EntityMentionFactory.build()
        entity_mention_repository.find_by_id.return_value = entity_mention

        result = await service.get_entity_mention(entity_mention.identifiedBy)

        assert result == entity_mention
        entity_mention_repository.find_by_id.assert_called_once_with(
            entity_mention.identifiedBy,
        )

    async def test_not_found_raises_error(
        self,
        service: EntityService,
        entity_mention_repository: MagicMock,
    ) -> None:
        identifier = EntityMentionIdentifierFactory.build()
        entity_mention_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError) as exc_info:
            await service.get_entity_mention(identifier)

        assert exc_info.value.entity_type == "EntityMention"
