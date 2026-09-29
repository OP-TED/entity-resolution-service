"""Repository abstractions and MongoDB implementations for Request Registry records."""

from abc import abstractmethod
from datetime import UTC, datetime
from typing import Any

from erspec.models.core import EntityMentionIdentifier
from pymongo.errors import ConnectionFailure, DuplicateKeyError, PyMongoError

from ers.commons.adapters.repository import (
    AsyncReadRepository,
    AsyncWriteRepository,
    BaseMongoRepository,
)
from ers.request_registry.domain.errors import (
    DuplicateTriadError,
    RegistryConnectionError,
    RepositoryOperationError,
)
from ers.request_registry.domain.records import (
    LookupRequestRecord,
    ResolutionRequestRecord,
    TriadKey,
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

    @abstractmethod
    async def exists_by_source(self, source_id: str) -> bool:
        """Return True if at least one resolution request exists for the given source."""

    @abstractmethod
    async def find_contexts_by_triads(
        self, identifiers: list[EntityMentionIdentifier]
    ) -> dict[TriadKey, str | None]:
        """Return context values keyed by triad for a batch of identifiers.

        Args:
            identifiers: The mention triads to look up.

        Returns:
            A dict mapping each TriadKey to its stored context value, or None
            if the context field is absent on the record (legacy records).
        """


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
            raise RegistryConnectionError(str(exc)) from exc
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

    async def exists_by_source(self, source_id: str) -> bool:
        """Return True if at least one resolution request exists for the given source."""
        doc = await self._collection.find_one(
            {"identifiedBy.source_id": source_id},
            projection={"_id": 1},
        )
        return doc is not None

    async def find_contexts_by_triads(
        self, identifiers: list[EntityMentionIdentifier]
    ) -> dict[TriadKey, str | None]:
        """Return context values keyed by triad for a batch of identifiers.

        Args:
            identifiers: The mention triads to look up.

        Returns:
            A dict mapping each TriadKey to its stored context value, or None
            if the context field is absent on the document (legacy records).
        """
        if not identifiers:
            return {}
        id_to_key: dict[str, TriadKey] = {
            self._triad_id(i): TriadKey.from_identifier(i)
            for i in identifiers
        }
        cursor = self._collection.find(
            {"_id": {"$in": list(id_to_key.keys())}},
            {"_id": 1, "context": 1},
        )
        result: dict[TriadKey, str | None] = {}
        async for doc in cursor:
            key = id_to_key[doc["_id"]]
            result[key] = doc.get("context")
        return result


class MongoLookupStateRepository(BaseMongoRepository[LookupRequestRecord, str]):
    """MongoDB-backed repository for per-source snapshot state.

    Uses source_id as the MongoDB _id via BaseMongoRepository.
    """

    _model_class = LookupRequestRecord
    _id_field = "source_id"
    _collection_name = "lookup_states"

    def _from_document(self, doc: dict[str, Any]) -> LookupRequestRecord:
        """Convert a MongoDB document to LookupRequestRecord, restoring UTC tzinfo.

        PyMongo returns datetime objects as naive UTC. The LookupRequestRecord
        validator requires timezone-aware datetimes, so we add UTC tzinfo here.
        """
        doc[self._id_field] = doc.pop("_id")
        for field in ("last_snapshot", "updated_at"):
            val = doc.get(field)
            if isinstance(val, datetime) and val.tzinfo is None:
                doc[field] = val.replace(tzinfo=UTC)
        return self._model_class.model_validate(doc)

    async def get(self, source_id: str) -> LookupRequestRecord | None:
        """Return the snapshot state for a source. Returns None if not found."""
        return await self.find_by_id(source_id)

    async def upsert(self, state: LookupRequestRecord) -> LookupRequestRecord:
        """Insert or replace the snapshot state for the given source_id."""
        return await self.save(state)
