"""Repository abstractions and MongoDB implementations for Request Registry records."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from erspec.models.core import EntityMentionIdentifier
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import ConnectionFailure, DuplicateKeyError, PyMongoError

from ers.commons.adapters.repository import BaseMongoRepository
from ers.request_registry.domain.records import LookupRequestRecord, LookupState, ResolutionRequestRecord
from ers.request_registry.services.exceptions import (
    DuplicateTriadError,
    RepositoryConnectionError,
    RepositoryOperationError,
)


# ---------------------------------------------------------------------------
# ResolutionRequestRepository
# ---------------------------------------------------------------------------


class ResolutionRequestRepository(ABC):
    """Port for ResolutionRequestRecord persistence operations."""

    @abstractmethod
    async def store(self, record: ResolutionRequestRecord) -> ResolutionRequestRecord:
        """Insert a new record. Raises DuplicateTriadError if the triad already exists."""

    @abstractmethod
    async def find_by_triad(
        self, identifier: EntityMentionIdentifier
    ) -> ResolutionRequestRecord | None:
        """Find a record by its triad identifier. Returns None if not found."""

    @abstractmethod
    async def find_by_source_id(
        self, source_id: str, limit: int = 100, offset: int = 0
    ) -> list[ResolutionRequestRecord]:
        """Return a paginated list of records for a given source_id."""


class MongoResolutionRequestRepository(ResolutionRequestRepository):
    """MongoDB-backed repository for ResolutionRequestRecord.

    Does NOT extend BaseMongoRepository because the document _id is a computed
    composite key derived from the triad fields, not a field on the model itself.
    """

    def __init__(self, collection: AsyncCollection) -> None:
        self._collection = collection

    @staticmethod
    def _triad_id(identifier: EntityMentionIdentifier) -> str:
        """Compute the MongoDB _id as a composite of the three triad fields."""
        return f"{identifier.source_id}::{identifier.request_id}::{identifier.entity_type}"

    def _to_document(self, record: ResolutionRequestRecord) -> dict[str, Any]:
        doc = record.model_dump(mode="json")
        doc["_id"] = self._triad_id(record.identifier)
        return doc

    def _from_document(self, doc: dict[str, Any]) -> ResolutionRequestRecord:
        doc = dict(doc)
        doc.pop("_id")
        return ResolutionRequestRecord.model_validate(doc)

    async def store(self, record: ResolutionRequestRecord) -> ResolutionRequestRecord:
        doc = self._to_document(record)
        try:
            await self._collection.insert_one(doc)
        except DuplicateKeyError:
            raise DuplicateTriadError(record.identifier)
        except ConnectionFailure as exc:
            raise RepositoryConnectionError(str(exc)) from exc
        except PyMongoError as exc:
            raise RepositoryOperationError(str(exc)) from exc
        return record

    async def find_by_triad(
        self, identifier: EntityMentionIdentifier
    ) -> ResolutionRequestRecord | None:
        doc = await self._collection.find_one({"_id": self._triad_id(identifier)})
        if doc is None:
            return None
        return self._from_document(doc)

    async def find_by_source_id(
        self, source_id: str, limit: int = 100, offset: int = 0
    ) -> list[ResolutionRequestRecord]:
        cursor = (
            self._collection.find({"identifier.source_id": source_id})
            .skip(offset)
            .limit(limit)
        )
        return [self._from_document(doc) async for doc in cursor]


# ---------------------------------------------------------------------------
# LookupRequestRepository
# ---------------------------------------------------------------------------


class LookupRequestRepository(ABC):
    """Port for LookupRequestRecord persistence operations (append-only log)."""

    @abstractmethod
    async def store(self, record: LookupRequestRecord) -> LookupRequestRecord:
        """Append a new lookup request record. Never raises on duplicate — the
        collection is append-only and has no uniqueness constraint."""

    @abstractmethod
    async def find_by_source_id(
        self, source_id: str, since: datetime | None = None
    ) -> list[LookupRequestRecord]:
        """Return all lookup request records for a source, optionally filtered
        to records with requested_at >= since."""


# ---------------------------------------------------------------------------
# LookupStateRepository
# ---------------------------------------------------------------------------


class LookupStateRepository(ABC):
    """Port for LookupState persistence operations."""

    @abstractmethod
    async def get(self, source_id: str) -> LookupState | None:
        """Return the LookupState for a source. Returns None if not found."""

    @abstractmethod
    async def upsert(self, state: LookupState) -> LookupState:
        """Insert or replace the LookupState for the given source_id."""


class MongoLookupStateRepository(BaseMongoRepository[LookupState, str], LookupStateRepository):
    """MongoDB-backed repository for LookupState.

    Uses source_id as the MongoDB _id via BaseMongoRepository with _id_field = "source_id".
    The inherited save() method performs an upsert via replace_one.
    """

    _model_class = LookupState
    _id_field = "source_id"

    async def get(self, source_id: str) -> LookupState | None:
        return await self.find_by_id(source_id)

    async def upsert(self, state: LookupState) -> LookupState:
        return await self.save(state)
