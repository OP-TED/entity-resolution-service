"""Unit tests for RequestRegistryService.

Repositories are mocked; SHA256ContentHasher is used real to verify hash correctness.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, create_autospec, patch

import pytest
from erspec.models.core import EntityMention, EntityMentionIdentifier

from ers.commons.adapters.hasher import SHA256ContentHasher
from ers.rdf_mention_parser.domain.rdf_mapping_config import EntityTypeConfig, RDFMappingConfig
from ers.request_registry.adapters.records_repository import (
    MongoLookupStateRepository,
    MongoResolutionRequestRepository,
)
from ers.request_registry.domain.records import LookupRequestRecord, ResolutionRequestRecord
from ers.request_registry.services.exceptions import (
    IdempotencyConflictError,
    SnapshotRegressionError,
)
from ers.request_registry.services.request_registry_service import RequestRegistryService

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

SOURCE_ID = "src-001"
REQUEST_ID = "req-001"
ENTITY_TYPE = "ORGANISATION"
CONTENT = '{"name": "Acme Corp"}'
CONTENT_TYPE = "application/ld+json"


def _identifier() -> EntityMentionIdentifier:
    return EntityMentionIdentifier(
        source_id=SOURCE_ID,
        request_id=REQUEST_ID,
        entity_type=ENTITY_TYPE,
    )


def _entity_mention(content: str = CONTENT) -> EntityMention:
    return EntityMention(
        identifiedBy=_identifier(),
        content=content,
        content_type=CONTENT_TYPE,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def resolution_repo() -> AsyncMock:
    return create_autospec(MongoResolutionRequestRepository, instance=True)


@pytest.fixture
def lookup_repo() -> AsyncMock:
    return create_autospec(MongoLookupStateRepository, instance=True)


@pytest.fixture
def hasher() -> SHA256ContentHasher:
    return SHA256ContentHasher()


@pytest.fixture
def rdf_config() -> RDFMappingConfig:
    return RDFMappingConfig(
        namespaces={"ex": "http://example.org/"},
        entity_types={
            "organisation": EntityTypeConfig(
                rdf_type="ex:Organization",
                fields={"name": "ex:name"},
            )
        },
    )


@pytest.fixture
def mock_parse_entity_mention():
    with patch(
        "ers.request_registry.services.request_registry_service.parse_entity_mention",
        return_value={"name": "Acme Corp"},
    ) as mock:
        yield mock


@pytest.fixture
def service(
    resolution_repo: AsyncMock,
    lookup_repo: AsyncMock,
    hasher: SHA256ContentHasher,
    rdf_config: RDFMappingConfig,
) -> RequestRegistryService:
    return RequestRegistryService(
        resolution_repo=resolution_repo,
        lookup_repo=lookup_repo,
        hasher=hasher,
        rdf_config=rdf_config,
    )


# ---------------------------------------------------------------------------
# register_resolution_request — new registration
# ---------------------------------------------------------------------------


class TestRegisterResolutionRequest:
    async def test_new_registration_stores_record(
        self,
        service: RequestRegistryService,
        resolution_repo: AsyncMock,
        mock_parse_entity_mention,
    ) -> None:
        resolution_repo.find_by_triad.return_value = None
        resolution_repo.store.side_effect = lambda r: r

        result = await service.register_resolution_request(_entity_mention())

        resolution_repo.store.assert_called_once()
        assert result.identifiedBy == _identifier()

    async def test_new_registration_computes_correct_sha256_hash(
        self,
        service: RequestRegistryService,
        resolution_repo: AsyncMock,
        mock_parse_entity_mention,
    ) -> None:
        resolution_repo.find_by_triad.return_value = None
        resolution_repo.store.side_effect = lambda r: r

        result = await service.register_resolution_request(_entity_mention())

        expected_hash = SHA256ContentHasher().hash(CONTENT)
        assert result.content_hash == expected_hash

    async def test_new_registration_sets_utc_received_at(
        self,
        service: RequestRegistryService,
        resolution_repo: AsyncMock,
        mock_parse_entity_mention,
    ) -> None:
        resolution_repo.find_by_triad.return_value = None
        resolution_repo.store.side_effect = lambda r: r

        before = datetime.now(UTC)
        result = await service.register_resolution_request(_entity_mention())
        after = datetime.now(UTC)

        assert result.received_at.tzinfo is not None
        assert before <= result.received_at <= after

    # --- idempotent replay ---

    async def test_idempotent_replay_returns_existing_without_storing(
        self,
        service: RequestRegistryService,
        resolution_repo: AsyncMock,
        hasher: SHA256ContentHasher,
    ) -> None:
        mention = _entity_mention()
        existing = ResolutionRequestRecord(
            **mention.model_dump(),
            content_hash=hasher.hash(CONTENT),
            received_at=datetime.now(UTC),
        )
        resolution_repo.find_by_triad.return_value = existing

        result = await service.register_resolution_request(mention)

        resolution_repo.store.assert_not_called()
        assert result is existing

    # --- idempotency conflict ---

    async def test_conflict_raises_idempotency_conflict_error(
        self,
        service: RequestRegistryService,
        resolution_repo: AsyncMock,
    ) -> None:
        mention = _entity_mention()
        existing = ResolutionRequestRecord(
            **mention.model_dump(),
            content_hash="a" * 64,  # different hash
            received_at=datetime.now(UTC),
        )
        resolution_repo.find_by_triad.return_value = existing

        with pytest.raises(IdempotencyConflictError) as exc_info:
            await service.register_resolution_request(mention)

        assert exc_info.value.identifier == _identifier()

    async def test_conflict_does_not_call_store(
        self,
        service: RequestRegistryService,
        resolution_repo: AsyncMock,
    ) -> None:
        mention = _entity_mention()
        existing = ResolutionRequestRecord(
            **mention.model_dump(),
            content_hash="b" * 64,
            received_at=datetime.now(UTC),
        )
        resolution_repo.find_by_triad.return_value = existing

        with pytest.raises(IdempotencyConflictError):
            await service.register_resolution_request(mention)

        resolution_repo.store.assert_not_called()

    # --- empty content guard ---

    async def test_empty_content_raises_value_error_before_repo_calls(
        self,
        service: RequestRegistryService,
        resolution_repo: AsyncMock,
    ) -> None:
        empty_mention = _entity_mention(content="")

        with pytest.raises(ValueError, match="empty"):
            await service.register_resolution_request(empty_mention)

        resolution_repo.find_by_triad.assert_not_called()
        resolution_repo.store.assert_not_called()


# ---------------------------------------------------------------------------
# advance_snapshot
# ---------------------------------------------------------------------------


class TestAdvanceSnapshot:
    async def test_first_call_creates_new_state(
        self,
        service: RequestRegistryService,
        lookup_repo: AsyncMock,
    ) -> None:
        lookup_repo.get.return_value = None
        snapshot_time = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        lookup_repo.upsert.side_effect = lambda s: s

        result = await service.advance_snapshot(SOURCE_ID, snapshot_time)

        lookup_repo.upsert.assert_called_once()
        assert result.source_id == SOURCE_ID
        assert result.last_snapshot == snapshot_time

    async def test_subsequent_call_advances_snapshot(
        self,
        service: RequestRegistryService,
        lookup_repo: AsyncMock,
    ) -> None:
        t1 = datetime(2026, 3, 1, tzinfo=UTC)
        t2 = datetime(2026, 3, 2, tzinfo=UTC)
        current = LookupRequestRecord(source_id=SOURCE_ID, last_snapshot=t1, updated_at=t1)
        lookup_repo.get.return_value = current
        lookup_repo.upsert.side_effect = lambda s: s

        result = await service.advance_snapshot(SOURCE_ID, t2)

        lookup_repo.upsert.assert_called_once()
        assert result.last_snapshot == t2

    async def test_regression_raises_snapshot_regression_error(
        self,
        service: RequestRegistryService,
        lookup_repo: AsyncMock,
    ) -> None:
        t1 = datetime(2026, 3, 5, tzinfo=UTC)
        t_earlier = datetime(2026, 3, 1, tzinfo=UTC)
        current = LookupRequestRecord(source_id=SOURCE_ID, last_snapshot=t1, updated_at=t1)
        lookup_repo.get.return_value = current

        with pytest.raises(SnapshotRegressionError) as exc_info:
            await service.advance_snapshot(SOURCE_ID, t_earlier)

        assert exc_info.value.source_id == SOURCE_ID
        assert exc_info.value.current == t1
        assert exc_info.value.attempted == t_earlier

    async def test_regression_does_not_call_upsert(
        self,
        service: RequestRegistryService,
        lookup_repo: AsyncMock,
    ) -> None:
        t1 = datetime(2026, 3, 5, tzinfo=UTC)
        current = LookupRequestRecord(source_id=SOURCE_ID, last_snapshot=t1, updated_at=t1)
        lookup_repo.get.return_value = current

        with pytest.raises(SnapshotRegressionError):
            await service.advance_snapshot(SOURCE_ID, t1)  # equal — also a regression

        lookup_repo.upsert.assert_not_called()
