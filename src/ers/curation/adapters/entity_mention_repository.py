from abc import abstractmethod

from erspec.models.core import EntityMention, EntityMentionIdentifier

from ers.commons.adapters.entity_mention_repository import (
    EntityMentionRepository,
    MongoEntityMentionRepository,
)


class EntityMentionCurationRepository(EntityMentionRepository):
    """Read-only repository for entity mention retrieval."""

    @abstractmethod
    async def find_by_identifiers(
        self,
        identifiers: list[EntityMentionIdentifier],
        limit: int | None = None,
    ) -> list[EntityMention]:
        """Batch-fetch entity mentions by their identifiers."""

    @abstractmethod
    async def search_identifiers(
        self,
        text: str,
    ) -> list[EntityMentionIdentifier]:
        """Full-text search entity mentions and return matching identifiers."""


class MongoEntityMentionCurationRepository(
    MongoEntityMentionRepository,
    EntityMentionCurationRepository,
):
    async def find_by_identifiers(
        self,
        identifiers: list[EntityMentionIdentifier],
        limit: int | None = None,
    ) -> list[EntityMention]:
        id_docs = [i.model_dump() for i in identifiers]
        cursor = self._collection.find({"_id": {"$in": id_docs}})
        if limit is not None:
            cursor = cursor.limit(limit)
        return [self._from_document(doc) async for doc in cursor]

    async def search_identifiers(
        self,
        text: str,
    ) -> list[EntityMentionIdentifier]:
        cursor = self._collection.find(
            {"$text": {"$search": text}},
            projection={"_id": 1},
        )
        return [EntityMentionIdentifier.model_validate(doc["_id"]) async for doc in cursor]
