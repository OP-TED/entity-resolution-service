from typing import Any

from erspec.models.core import EntityMention, EntityMentionIdentifier

from ers.adapters.mongodb.base import BaseMongoRepository
from ers.application.ports.entity_mention_repository import (
    EntityMentionRepository as EntityMentionRepositoryPort,
)


class MongoEntityMentionRepository(
    BaseMongoRepository[EntityMention, EntityMentionIdentifier],
    EntityMentionRepositoryPort,
):
    _model_class = EntityMention
    _id_field = "identifiedBy"

    def _identifier_to_id(self, identifier: EntityMentionIdentifier) -> dict[str, str]:
        return {
            "source_id": identifier.source_id,
            "request_id": identifier.request_id,
            "entity_type": identifier.entity_type,
        }

    def _to_document(self, entity: EntityMention) -> dict[str, Any]:
        doc = entity.model_dump(mode="python")
        doc.pop("object_description", None)
        doc["_id"] = self._identifier_to_id(entity.identifiedBy)
        del doc["identifiedBy"]
        return doc

    def _from_document(self, doc: dict[str, Any]) -> EntityMention:
        doc["identifiedBy"] = doc.pop("_id")
        doc.pop("object_description", None)
        return self._model_class.model_validate(doc)

    async def find_by_id(
        self, entity_id: EntityMentionIdentifier
    ) -> EntityMention | None:
        doc = await self._collection.find_one(
            {"_id": self._identifier_to_id(entity_id)}
        )
        if doc is None:
            return None
        return self._from_document(doc)

    async def find_by_identifiers(
        self,
        identifiers: list[EntityMentionIdentifier],
        limit: int | None = None,
    ) -> list[EntityMention]:
        id_docs = [self._identifier_to_id(i) for i in identifiers]
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
        return [
            EntityMentionIdentifier.model_validate(doc["_id"]) async for doc in cursor
        ]
