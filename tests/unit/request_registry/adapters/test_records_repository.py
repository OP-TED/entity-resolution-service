"""Unit tests for MongoResolutionRequestRepository and MongoLookupStateRepository.

AsyncCollection is mocked — no real MongoDB required.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from erspec.models.core import EntityMentionIdentifier
from pymongo.errors import ConnectionFailure, DuplicateKeyError, PyMongoError

from ers.request_registry.adapters.records_repository import (
    MongoLookupStateRepository,
    MongoResolutionRequestRepository,
)
from ers.request_registry.domain.records import LookupRequestRecord, ResolutionRequestRecord
from ers.request_registry.services.exceptions import (
    DuplicateTriadError,
    RepositoryConnectionError,
    RepositoryOperationError,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

SOURCE_ID = "src-001"
REQUEST_ID = "req-001"
ENTITY_TYPE = "ORGANISATION"
CONTENT = '{"name": "Acme Corp"}'
VALID_HASH = "a" * 64


def _identifier() -> EntityMentionIdentifier:
    return EntityMentionIdentifier(
        source_id=SOURCE_ID,
        request_id=REQUEST_ID,
        entity_type=ENTITY_TYPE,
    )


def _record() -> ResolutionRequestRecord:
    return ResolutionRequestRecord(
        identifiedBy=_identifier(),
        content=CONTENT,
        content_type="application/ld+json",
        content_hash=VALID_HASH,
        received_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def async_collection() -> AsyncMock:
    col = AsyncMock()
    # make find() return an async iterable that yields nothing by default
    col.find.return_value = _async_iter([])
    return col


@pytest.fixture
def repo(async_collection: AsyncMock) -> MongoResolutionRequestRepository:
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=async_collection)
    return MongoResolutionRequestRepository(db)


def _async_iter(items: list):
    """Helper: return an object that satisfies `async for doc in ...`."""

    class _AsyncIter:
        def __aiter__(self):
            return self

        async def __anext__(self):
            if not items:
                raise StopAsyncIteration
            return items.pop(0)

        def skip(self, n):
            return self

        def limit(self, n):
            return self

    return _AsyncIter()


# ---------------------------------------------------------------------------
# MongoResolutionRequestRepository — _triad_id
# ---------------------------------------------------------------------------


class TestTriadId:
    def test_produces_composite_key(self, repo: MongoResolutionRequestRepository) -> None:
        identifier = _identifier()
        expected = f"{SOURCE_ID}::{REQUEST_ID}::{ENTITY_TYPE}"
        assert repo._triad_id(identifier) == expected

    def test_uses_double_colon_separator(self, repo: MongoResolutionRequestRepository) -> None:
        identifier = _identifier()
        result = repo._triad_id(identifier)
        assert "::" in result

    def test_consistent_for_same_identifier(self, repo: MongoResolutionRequestRepository) -> None:
        identifier = _identifier()
        assert repo._triad_id(identifier) == repo._triad_id(identifier)


# ---------------------------------------------------------------------------
# MongoResolutionRequestRepository — store
# ---------------------------------------------------------------------------


class TestStore:
    async def test_calls_insert_one_with_id_set(
        self,
        repo: MongoResolutionRequestRepository,
        async_collection: AsyncMock,
    ) -> None:
        record = _record()
        async_collection.insert_one.return_value = None

        await repo.store(record)

        async_collection.insert_one.assert_called_once()
        doc_arg = async_collection.insert_one.call_args[0][0]
        assert doc_arg["_id"] == repo._triad_id(_identifier())

    async def test_returns_record_on_success(
        self,
        repo: MongoResolutionRequestRepository,
        async_collection: AsyncMock,
    ) -> None:
        record = _record()
        async_collection.insert_one.return_value = None

        result = await repo.store(record)

        assert result is record

    async def test_duplicate_key_error_raises_duplicate_triad_error(
        self,
        repo: MongoResolutionRequestRepository,
        async_collection: AsyncMock,
    ) -> None:
        async_collection.insert_one.side_effect = DuplicateKeyError("dup")

        with pytest.raises(DuplicateTriadError) as exc_info:
            await repo.store(_record())

        assert exc_info.value.identifier == _identifier()

    async def test_connection_failure_raises_repository_connection_error(
        self,
        repo: MongoResolutionRequestRepository,
        async_collection: AsyncMock,
    ) -> None:
        async_collection.insert_one.side_effect = ConnectionFailure("timeout")

        with pytest.raises(RepositoryConnectionError):
            await repo.store(_record())

    async def test_pymongo_error_raises_repository_operation_error(
        self,
        repo: MongoResolutionRequestRepository,
        async_collection: AsyncMock,
    ) -> None:
        async_collection.insert_one.side_effect = PyMongoError("write failed")

        with pytest.raises(RepositoryOperationError):
            await repo.store(_record())


# ---------------------------------------------------------------------------
# MongoResolutionRequestRepository — find_by_triad
# ---------------------------------------------------------------------------


class TestFindByTriad:
    async def test_queries_by_computed_id(
        self,
        repo: MongoResolutionRequestRepository,
        async_collection: AsyncMock,
    ) -> None:
        async_collection.find_one.return_value = None

        await repo.find_by_triad(_identifier())

        async_collection.find_one.assert_called_once_with({"_id": repo._triad_id(_identifier())})

    async def test_returns_none_when_not_found(
        self,
        repo: MongoResolutionRequestRepository,
        async_collection: AsyncMock,
    ) -> None:
        async_collection.find_one.return_value = None

        result = await repo.find_by_triad(_identifier())

        assert result is None

    async def test_returns_record_when_found(
        self,
        repo: MongoResolutionRequestRepository,
        async_collection: AsyncMock,
    ) -> None:
        record = _record()
        doc = repo._to_document(record)
        async_collection.find_one.return_value = doc

        result = await repo.find_by_triad(_identifier())

        assert result is not None
        assert result.identifiedBy == _identifier()
        assert result.content_hash == VALID_HASH


# ---------------------------------------------------------------------------
# MongoResolutionRequestRepository — _from_document round-trip
# ---------------------------------------------------------------------------


class TestFromDocument:
    def test_maps_id_back_to_identified_by(self, repo: MongoResolutionRequestRepository) -> None:
        record = _record()
        doc = repo._to_document(record)

        result = repo._from_document(doc)

        assert result.identifiedBy.source_id == SOURCE_ID
        assert result.identifiedBy.request_id == REQUEST_ID
        assert result.identifiedBy.entity_type == ENTITY_TYPE
        assert result.content_hash == VALID_HASH

    def test_original_doc_not_mutated(self, repo: MongoResolutionRequestRepository) -> None:
        record = _record()
        doc = repo._to_document(record)

        repo._from_document(doc)

        assert "_id" in doc


# ---------------------------------------------------------------------------
# MongoLookupStateRepository — upsert delegates to save (replace_one upsert)
# ---------------------------------------------------------------------------


class TestMongoLookupStateRepository:
    @pytest.fixture
    def lookup_collection(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def lookup_repo(self, lookup_collection: AsyncMock) -> MongoLookupStateRepository:
        db = MagicMock()
        db.__getitem__ = MagicMock(return_value=lookup_collection)
        return MongoLookupStateRepository(db)

    async def test_upsert_calls_replace_one_with_upsert_true(
        self,
        lookup_repo: MongoLookupStateRepository,
        lookup_collection: AsyncMock,
    ) -> None:
        now = datetime.now(UTC)
        state = LookupRequestRecord(source_id=SOURCE_ID, last_snapshot=now, updated_at=now)
        lookup_collection.replace_one.return_value = MagicMock()

        result = await lookup_repo.upsert(state)

        lookup_collection.replace_one.assert_called_once()
        call_kwargs = lookup_collection.replace_one.call_args
        assert call_kwargs.kwargs.get("upsert") is True or (
            len(call_kwargs.args) >= 3
            and call_kwargs.args[2] is True
            or call_kwargs.kwargs.get("upsert", False)
        )
        assert result is state

    async def test_get_returns_none_for_unknown_source(
        self,
        lookup_repo: MongoLookupStateRepository,
        lookup_collection: AsyncMock,
    ) -> None:
        lookup_collection.find_one.return_value = None

        result = await lookup_repo.get("unknown-src")

        assert result is None

    async def test_get_returns_state_when_found(
        self,
        lookup_repo: MongoLookupStateRepository,
        lookup_collection: AsyncMock,
    ) -> None:
        now = datetime.now(UTC)
        state = LookupRequestRecord(source_id=SOURCE_ID, last_snapshot=now, updated_at=now)
        doc = state.model_dump(mode="json")
        doc["_id"] = SOURCE_ID
        lookup_collection.find_one.return_value = doc

        result = await lookup_repo.get(SOURCE_ID)

        assert result is not None
        assert result.source_id == SOURCE_ID
