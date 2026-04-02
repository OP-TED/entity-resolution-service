from abc import ABC, abstractmethod
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel
from pymongo.asynchronous.database import AsyncDatabase

T = TypeVar("T", bound=BaseModel)
ID = TypeVar("ID")


class AsyncReadRepository[T, ID](ABC):
    """Abstract async read-only repository."""

    @abstractmethod
    async def find_by_id(self, entity_id: ID) -> T | None:
        """Find an entity by its identifier. Returns None if not found."""


class AsyncWriteRepository[T, ID](ABC):
    """Abstract async write repository."""

    @abstractmethod
    async def save(self, entity: T) -> T:
        """Persist an entity. Handles both creation and updates."""


class BaseMongoRepository(AsyncReadRepository[T, ID], AsyncWriteRepository[T, ID]):
    """Generic base for MongoDB repositories backed by Pydantic models.

    Handles bidirectional conversion between Pydantic models and MongoDB documents,
    mapping the model's identity field to MongoDB's ``_id``.
    """

    _model_class: type[T]
    _id_field: str = "id"
    _collection_name: ClassVar[str]

    def __init__(self, database: AsyncDatabase) -> None:
        self._collection = database[self._collection_name]

    def _to_document(self, entity: T) -> dict[str, Any]:
        doc = entity.model_dump(exclude={"object_description"})
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
