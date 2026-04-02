"""Unit tests for Request Registry domain records."""

from datetime import UTC, datetime

import pytest
from erspec.models.core import EntityMentionIdentifier
from pydantic import ValidationError

from ers.request_registry.domain.records import (
    LookupRequestRecord,
    ResolutionRequestRecord,
)

# A valid SHA-256 hex digest used across tests (SHA-256 of empty string).
VALID_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def identifier() -> EntityMentionIdentifier:
    return EntityMentionIdentifier(
        source_id="src-001",
        request_id="req-001",
        entity_type="ORGANISATION",
    )


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# ResolutionRequestRecord
# ---------------------------------------------------------------------------


class TestResolutionRequestRecord:
    def test_instantiation_with_valid_data(
        self,
        identifier: EntityMentionIdentifier,
        now: datetime,
    ) -> None:
        record = ResolutionRequestRecord(
            identifiedBy=identifier,
            content='{"name": "Acme Corp"}',
            content_type="application/ld+json",
            content_hash=VALID_HASH,
            received_at=now,
        )
        assert record.identifiedBy == identifier
        assert record.content == '{"name": "Acme Corp"}'
        assert record.content_type == "application/ld+json"
        assert record.content_hash == VALID_HASH
        assert record.received_at == now
        assert record.parsed_representation is None

    def test_parsed_representation_accepts_value(
        self,
        identifier: EntityMentionIdentifier,
        now: datetime,
    ) -> None:
        record = ResolutionRequestRecord(
            identifiedBy=identifier,
            content='{"name": "Acme Corp"}',
            content_type="application/ld+json",
            content_hash=VALID_HASH,
            received_at=now,
            parsed_representation='{"name": "Acme"}',
        )
        assert record.parsed_representation == '{"name": "Acme"}'

    def test_invalid_content_hash_too_short(
        self,
        identifier: EntityMentionIdentifier,
        now: datetime,
    ) -> None:
        with pytest.raises(ValidationError):
            ResolutionRequestRecord(
                identifiedBy=identifier,
                content='{"name": "Acme Corp"}',
                content_type="application/ld+json",
                content_hash="abc123",
                received_at=now,
            )

    def test_invalid_content_hash_non_hex(
        self,
        identifier: EntityMentionIdentifier,
        now: datetime,
    ) -> None:
        with pytest.raises(ValidationError):
            ResolutionRequestRecord(
                identifiedBy=identifier,
                content='{"name": "Acme Corp"}',
                content_type="application/ld+json",
                content_hash="z" * 64,
                received_at=now,
            )

    def test_naive_received_at_is_rejected(
        self,
        identifier: EntityMentionIdentifier,
    ) -> None:
        with pytest.raises(ValidationError):
            ResolutionRequestRecord(
                identifiedBy=identifier,
                content='{"name": "Acme Corp"}',
                content_type="application/ld+json",
                content_hash=VALID_HASH,
                received_at=datetime(2024, 1, 1),  # naive — no tzinfo
            )


# ---------------------------------------------------------------------------
# LookupRequestRecord (per-source snapshot marker)
# ---------------------------------------------------------------------------


class TestLookupRequestRecord:
    def test_instantiation_with_valid_data(self, now: datetime) -> None:
        state = LookupRequestRecord(
            source_id="src-001",
            last_snapshot=now,
            updated_at=now,
        )
        assert state.source_id == "src-001"
        assert state.last_snapshot == now
        assert state.updated_at == now

    def test_last_snapshot_can_be_epoch(self) -> None:
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        state = LookupRequestRecord(
            source_id="src-001",
            last_snapshot=epoch,
            updated_at=datetime.now(UTC),
        )
        assert state.last_snapshot == epoch

    def test_accepts_future_timestamp(self) -> None:
        future = datetime(2099, 12, 31, tzinfo=UTC)
        state = LookupRequestRecord(
            source_id="src-001",
            last_snapshot=future,
            updated_at=future,
        )
        assert state.last_snapshot == future

    def test_frozen_rejects_last_snapshot_mutation(self, now: datetime) -> None:
        state = LookupRequestRecord(source_id="src-001", last_snapshot=now, updated_at=now)
        with pytest.raises(ValidationError):
            state.last_snapshot = datetime.now(UTC)  # type: ignore[misc]

    def test_updated_at_independent_from_last_snapshot(self) -> None:
        last_snapshot = datetime(2026, 1, 1, tzinfo=UTC)
        updated_at = datetime(2026, 3, 1, tzinfo=UTC)
        state = LookupRequestRecord(
            source_id="src-001",
            last_snapshot=last_snapshot,
            updated_at=updated_at,
        )
        assert state.last_snapshot != state.updated_at

    def test_naive_last_snapshot_is_rejected(self, now: datetime) -> None:
        with pytest.raises(ValidationError):
            LookupRequestRecord(
                source_id="src-001",
                last_snapshot=datetime(2024, 1, 1),  # naive
                updated_at=now,
            )

    def test_naive_updated_at_is_rejected(self, now: datetime) -> None:
        with pytest.raises(ValidationError):
            LookupRequestRecord(
                source_id="src-001",
                last_snapshot=now,
                updated_at=datetime(2024, 1, 1),  # naive
            )

    def test_updated_at_before_last_snapshot_is_rejected(self) -> None:
        t1 = datetime(2026, 6, 1, tzinfo=UTC)
        t2 = datetime(2026, 1, 1, tzinfo=UTC)  # earlier than t1
        with pytest.raises(ValidationError):
            LookupRequestRecord(source_id="src-001", last_snapshot=t1, updated_at=t2)
