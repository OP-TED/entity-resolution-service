from typing import Any

from erspec.models.core import EntityMention, EntityMentionIdentifier

from ers.commons.adapters import BaseMongoRepository
from ers.commons.adapters.repository import AsyncReadRepository, AsyncWriteRepository


class EntityMentionRepository(
    AsyncReadRepository[EntityMention, EntityMentionIdentifier],
    AsyncWriteRepository[EntityMention, EntityMentionIdentifier],
):
    """Repository for entity mention retrieval and saving."""


class MongoEntityMentionRepository(
    BaseMongoRepository[EntityMention, EntityMentionIdentifier],
    EntityMentionRepository,
):
    _model_class = EntityMention
    _id_field = "identifiedBy"

    def _to_document(self, entity: EntityMention) -> dict[str, Any]:
        doc = entity.model_dump(exclude={"identifiedBy", "object_description"})
        doc["_id"] = entity.identifiedBy.model_dump()
        return doc

    def _from_document(self, doc: dict[str, Any]) -> EntityMention:
        doc["identifiedBy"] = doc.pop("_id")
        doc.pop("object_description", None)
        return self._model_class.model_validate(doc)

    async def find_by_id(
        self, entity_id: EntityMentionIdentifier
    ) -> EntityMention | None:
        doc = await self._collection.find_one({"_id": entity_id.model_dump()})
        if doc is None:
            return None
        return self._from_document(doc)
