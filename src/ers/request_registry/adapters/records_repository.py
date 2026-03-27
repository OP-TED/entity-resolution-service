"""Repository abstractions and MongoDB implementations for Request Registry records."""

from abc import abstractmethod
from typing import Any

from erspec.models.core import EntityMentionIdentifier
from pymongo.errors import ConnectionFailure, DuplicateKeyError, PyMongoError

from ers.commons.adapters.repository import (
    AsyncReadRepository,
    AsyncWriteRepository,
    BaseMongoRepository,
)
from ers.request_registry.domain.records import LookupRequestRecord, ResolutionRequestRecord
from ers.request_registry.services.exceptions import (
    DuplicateTriadError,
    RepositoryConnectionError,
    RepositoryOperationError,
)


class ResolutionRequestRepository(
    AsyncReadRepository[ResolutionRequestRecord, str],
    AsyncWriteRepository[ResolutionRequestRecord, str],
):
    """Abstract repository for resolution request records."""

    @abstractmethod
    async def store(self, record: ResolutionRequestRecord) -> ResolutionRequestRecord:
        """Insert-only store for a new resolution request record."""

    @abstractmethod
    async def find_by_triad(
        self, identifier: EntityMentionIdentifier
    ) -> ResolutionRequestRecord | None:
        """Find a record by its identifier triad."""

    @abstractmethod
    async def find_by_source_id(
        self, source_id: str, limit: int = 100, offset: int = 0
    ) -> list[ResolutionRequestRecord]:
        """Return a paginated list of records for a given source_id."""


class MongoResolutionRequestRepository(
    BaseMongoRepository[ResolutionRequestRecord, str],
    ResolutionRequestRepository,
):
    """MongoDB-backed repository for ResolutionRequestRecord.

    Extends BaseMongoRepository with a computed composite _id derived from the
    triad fields. Overrides _to_document/_from_document for the custom key
    mapping and provides insert-only store() with domain error wrapping.
    """

    _model_class = ResolutionRequestRecord
    _collection_name = "resolution_requests"

    @staticmethod
    def _triad_id(identifier: EntityMentionIdentifier) -> str:
        """Compute the MongoDB _id as a composite of the three triad fields."""
        return f"{identifier.source_id}::{identifier.request_id}::{identifier.entity_type}"

    def _to_document(self, entity: ResolutionRequestRecord) -> dict[str, Any]:
        doc = entity.model_dump(mode="json")
        doc["_id"] = self._triad_id(entity.identifiedBy)
        return doc

    def _from_document(self, doc: dict[str, Any]) -> ResolutionRequestRecord:
        doc = dict(doc)
        doc.pop("_id")
        return ResolutionRequestRecord.model_validate(doc)

    async def store(self, record: ResolutionRequestRecord) -> ResolutionRequestRecord:
        """Insert-only store with domain-specific error wrapping."""
        doc = self._to_document(record)
        try:
            await self._collection.insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateTriadError(record.identifiedBy) from exc
        except ConnectionFailure as exc:
            raise RepositoryConnectionError(str(exc)) from exc
        except PyMongoError as exc:
            raise RepositoryOperationError(str(exc)) from exc
        return record

    async def find_by_triad(
        self, identifier: EntityMentionIdentifier
    ) -> ResolutionRequestRecord | None:
        """Find a record by its composite triad key."""
        return await self.find_by_id(self._triad_id(identifier))

    async def find_by_source_id(
        self, source_id: str, limit: int = 100, offset: int = 0
    ) -> list[ResolutionRequestRecord]:
        """Return a paginated list of records for a given source_id."""
        cursor = (
            self._collection.find({"identifiedBy.source_id": source_id}).skip(offset).limit(limit)
        )
        return [self._from_document(doc) async for doc in cursor]


class MongoLookupStateRepository(BaseMongoRepository[LookupRequestRecord, str]):
    """MongoDB-backed repository for per-source snapshot state.

    Uses source_id as the MongoDB _id via BaseMongoRepository.
    """

    _model_class = LookupRequestRecord
    _id_field = "source_id"
    _collection_name = "lookup_states"

    async def get(self, source_id: str) -> LookupRequestRecord | None:
        """Return the snapshot state for a source. Returns None if not found."""
        return await self.find_by_id(source_id)

    async def upsert(self, state: LookupRequestRecord) -> LookupRequestRecord:
        """Insert or replace the snapshot state for the given source_id."""
        return await self.save(state)
