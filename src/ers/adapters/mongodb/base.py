from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from pymongo.asynchronous.collection import AsyncCollection

from ers.application import AsyncReadRepository, AsyncWriteRepository

T = TypeVar("T", bound=BaseModel)
ID = TypeVar("ID")


class BaseMongoRepository(
    Generic[T, ID], AsyncReadRepository[T, ID], AsyncWriteRepository[T, ID]
):
    """Generic base for MongoDB repositories backed by Pydantic models.

    Handles bidirectional conversion between Pydantic models and MongoDB documents,
    mapping the model's identity field to MongoDB's ``_id``.
    """

    _model_class: type[T]
    _id_field: str = "id"

    def __init__(self, collection: AsyncCollection) -> None:
        self._collection = collection

    def _to_document(self, entity: T) -> dict[str, Any]:
        doc = entity.model_dump(mode="python")
        doc.pop("object_description", None)
        doc["_id"] = doc.pop(self._id_field)
        return doc

    def _from_document(self, doc: dict[str, Any]) -> T:
        doc[self._id_field] = doc.pop("_id")
        doc.pop("object_description", None)
        return self._model_class.model_validate(doc)

    async def find_by_id(self, entity_id: ID) -> T | None:
        doc = await self._collection.find_one({"_id": entity_id})
        if doc is None:
            return None
        return self._from_document(doc)

    async def save(self, entity: T) -> T:
        doc = self._to_document(entity)
        await self._collection.replace_one(
            {"_id": doc["_id"]},
            doc,
            upsert=True,
        )
        return entity
