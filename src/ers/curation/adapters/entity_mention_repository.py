from abc import abstractmethod

from erspec.models.core import EntityMention, EntityMentionIdentifier

from ers.request_registry.adapters.records_repository import (
    MongoResolutionRequestRepository,
    ResolutionRequestRepository,
)


class EntityMentionCurationRepository(ResolutionRequestRepository):
    """Repository for entity mention retrieval in curation.

    Extends ``ResolutionRequestRepository`` with batch-fetch and full-text
    search capabilities needed by curation services.
    """

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
    EntityMentionCurationRepository, MongoResolutionRequestRepository
):
    async def find_by_identifiers(
        self,
        identifiers: list[EntityMentionIdentifier],
        limit: int | None = None,
    ) -> list[EntityMention]:
        triad_ids = [self._triad_id(i) for i in identifiers]
        cursor = self._collection.find({"_id": {"$in": triad_ids}})
        if limit is not None:
            cursor = cursor.limit(limit)
        return [self._from_document(doc) async for doc in cursor]

    async def search_identifiers(
        self,
        text: str,
    ) -> list[EntityMentionIdentifier]:
        cursor = self._collection.find(
            {"$text": {"$search": text}},
            projection={"identifiedBy": 1, "_id": 0},
        )
        return [EntityMentionIdentifier.model_validate(doc["identifiedBy"]) async for doc in cursor]
