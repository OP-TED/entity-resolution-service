from unittest.mock import MagicMock, create_autospec

import pytest

from ers.commons.services.exceptions import NotFoundError
from ers.curation.adapters import (
    EntityMentionCurationRepository,
)
from ers.curation.services import EntityService
from tests.unit.factories import EntityMentionFactory, EntityMentionIdentifierFactory


@pytest.fixture
def entity_mention_repository() -> MagicMock:
    return create_autospec(EntityMentionCurationRepository, instance=True)


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
        entity_mention_repository.find_by_triad.return_value = entity_mention

        result = await service.get_entity_mention(entity_mention.identifiedBy)

        assert result == entity_mention
        entity_mention_repository.find_by_triad.assert_called_once_with(
            entity_mention.identifiedBy,
        )

    async def test_not_found_raises_error(
        self,
        service: EntityService,
        entity_mention_repository: MagicMock,
    ) -> None:
        identifier = EntityMentionIdentifierFactory.build()
        entity_mention_repository.find_by_triad.return_value = None

        with pytest.raises(NotFoundError) as exc_info:
            await service.get_entity_mention(identifier)

        assert exc_info.value.entity_type == "EntityMention"
