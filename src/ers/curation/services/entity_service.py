from erspec.models.core import EntityMention, EntityMentionIdentifier

from ers.commons.services.exceptions import NotFoundError
from ers.curation.adapters.entity_mention_repository import (
    EntityMentionCurationRepository,
)
from ers.curation.services._pymongo_translation import translate_mongo_errors


class EntityService:
    """Retrieves entity mentions for display."""

    def __init__(
        self,
        entity_mention_repository: EntityMentionCurationRepository,
    ) -> None:
        self._entity_mention_repository = entity_mention_repository

    @translate_mongo_errors
    async def get_entity_mention(
        self,
        identifier: EntityMentionIdentifier,
    ) -> EntityMention:
        """Retrieve an entity mention by its identifier.

        Raises:
            NotFoundError: If the entity mention does not exist.
        """
        entity = await self._entity_mention_repository.find_by_triad(identifier)
        if entity is None:
            raise NotFoundError(
                "EntityMention",
                f"{identifier.source_id}/{identifier.request_id}/{identifier.entity_type}",
            )
        return entity
