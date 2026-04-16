"""Unit tests for LookupService — coordinator gateway pattern."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers.ers_rest_api.domain.errors import ErrorCode
from ers.ers_rest_api.domain.lookup import BulkLookupRequest, LookupRequest
from ers.ers_rest_api.services.exceptions import MentionNotFoundError
from ers.ers_rest_api.services.lookup_service import LookupService
from ers.request_registry.domain.records import TriadKey
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_coordinator.services.resolution_coordinator_service import (
    ResolutionCoordinatorService,
)


@pytest.fixture
def coordinator() -> AsyncMock:
    return create_autospec(ResolutionCoordinatorService, instance=True)


@pytest.fixture
def registry_service() -> AsyncMock:
    mock = create_autospec(RequestRegistryService, instance=True)
    mock.get_contexts_for_triads.return_value = {}
    return mock


@pytest.fixture
def service(coordinator: AsyncMock, registry_service: AsyncMock) -> LookupService:
    return LookupService(resolution_coordinator=coordinator, registry_service=registry_service)


def _make_decision(
    source_id: str, request_id: str, entity_type: str = "ORGANISATION",
    cluster_id: str | None = None, updated_at: datetime | None = None,
) -> Decision:
    return Decision(
        id=f"decision-{request_id}",
        about_entity_mention=EntityMentionIdentifier(
            source_id=source_id,
            request_id=request_id,
            entity_type=entity_type,
        ),
        current_placement=ClusterReference(
            cluster_id=cluster_id or f"cluster-{request_id}",
            confidence_score=0.9,
            similarity_score=0.85,
        ),
        candidates=[],
        created_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC),
        updated_at=updated_at or datetime(2026, 3, 15, 11, 0, 0, tzinfo=UTC),
    )


class TestLookupService:
    async def test_known_mention_returns_lookup_response(
        self, service: LookupService, coordinator: AsyncMock
    ) -> None:
        coordinator.lookup_by_triad.return_value = _make_decision(
            "SYSTEM_A", "req-001", cluster_id="cluster-010",
            updated_at=datetime(2026, 3, 15, 11, 0, 0, tzinfo=UTC),
        )

        result = await service.handle_lookup("SYSTEM_A", "req-001", "ORGANISATION")

        assert result.cluster_reference.cluster_id == "cluster-010"
        assert result.last_updated == datetime(2026, 3, 15, 11, 0, 0, tzinfo=UTC)
        coordinator.lookup_by_triad.assert_awaited_once()

    async def test_uses_created_at_when_updated_at_is_none(
        self, service: LookupService, coordinator: AsyncMock
    ) -> None:
        decision = Decision(
            id="decision-002",
            about_entity_mention=EntityMentionIdentifier(
                source_id="SYSTEM_A", request_id="req-002", entity_type="ORGANISATION",
            ),
            current_placement=ClusterReference(
                cluster_id="cluster-011", confidence_score=0.85, similarity_score=0.80,
            ),
            candidates=[],
            created_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC),
            updated_at=None,
        )
        coordinator.lookup_by_triad.return_value = decision

        result = await service.handle_lookup("SYSTEM_A", "req-002", "ORGANISATION")

        assert result.last_updated == datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)

    async def test_unknown_mention_raises_not_found(
        self, service: LookupService, coordinator: AsyncMock
    ) -> None:
        coordinator.lookup_by_triad.return_value = None

        with pytest.raises(MentionNotFoundError):
            await service.handle_lookup("SYSTEM_UNKNOWN", "req-999", "ORGANISATION")

    async def test_propagates_coordinator_exception(
        self, service: LookupService, coordinator: AsyncMock
    ) -> None:
        coordinator.lookup_by_triad.side_effect = RuntimeError("store unavailable")

        with pytest.raises(RuntimeError, match="store unavailable"):
            await service.handle_lookup("SYSTEM_A", "req-001", "ORGANISATION")


BULK_REQUEST = BulkLookupRequest(
    mentions=[
        LookupRequest(
            identified_by=EntityMentionIdentifier(
                source_id="SRC_A", request_id="req-001", entity_type="ORGANISATION",
            ),
        ),
        LookupRequest(
            identified_by=EntityMentionIdentifier(
                source_id="SRC_B", request_id="req-002", entity_type="ORGANISATION",
            ),
        ),
    ],
)


class TestBulkLookupService:
    async def test_all_found(
        self, service: LookupService, coordinator: AsyncMock
    ) -> None:
        coordinator.lookup_by_triad.side_effect = [
            _make_decision("SRC_A", "req-001"),
            _make_decision("SRC_B", "req-002"),
        ]

        result = await service.handle_bulk_lookup(BULK_REQUEST)

        assert len(result.results) == 2
        assert result.results[0].cluster_reference.cluster_id == "cluster-req-001"
        assert result.results[1].cluster_reference.cluster_id == "cluster-req-002"
        assert all(r.error is None for r in result.results)

    async def test_not_found_collects_error(
        self, service: LookupService, coordinator: AsyncMock
    ) -> None:
        coordinator.lookup_by_triad.side_effect = [
            _make_decision("SRC_A", "req-001"),
            None,
        ]

        result = await service.handle_bulk_lookup(BULK_REQUEST)

        assert len(result.results) == 2
        assert result.results[0].error is None
        assert result.results[1].error is not None
        assert result.results[1].error.error_code == ErrorCode.MENTION_NOT_FOUND

    async def test_store_exception_collects_service_error(
        self, service: LookupService, coordinator: AsyncMock
    ) -> None:
        coordinator.lookup_by_triad.side_effect = [
            _make_decision("SRC_A", "req-001"),
            RuntimeError("store down"),
        ]

        result = await service.handle_bulk_lookup(BULK_REQUEST)

        assert len(result.results) == 2
        assert result.results[0].error is None
        assert result.results[1].error is not None
        assert result.results[1].error.error_code == ErrorCode.SERVICE_ERROR

    async def test_all_not_found(
        self, service: LookupService, coordinator: AsyncMock
    ) -> None:
        coordinator.lookup_by_triad.return_value = None

        result = await service.handle_bulk_lookup(BULK_REQUEST)

        assert len(result.results) == 2
        assert all(r.error is not None for r in result.results)
        assert all(r.error.error_code == ErrorCode.MENTION_NOT_FOUND for r in result.results)


class TestLookupServiceContext:
    async def test_context_included_when_registry_returns_it(
        self, service: LookupService, coordinator: AsyncMock, registry_service: AsyncMock
    ) -> None:
        decision = _make_decision("SYSTEM_A", "req-001", cluster_id="cluster-010")
        coordinator.lookup_by_triad.return_value = decision
        registry_service.get_contexts_for_triads.return_value = {
            TriadKey("SYSTEM_A", "req-001", "ORGANISATION"): "procurement ctx"
        }

        result = await service.handle_lookup("SYSTEM_A", "req-001", "ORGANISATION")

        assert result.context == "procurement ctx"

    async def test_context_is_none_when_not_in_registry(
        self, service: LookupService, coordinator: AsyncMock, registry_service: AsyncMock
    ) -> None:
        coordinator.lookup_by_triad.return_value = _make_decision("SYSTEM_A", "req-001")
        registry_service.get_contexts_for_triads.return_value = {}

        result = await service.handle_lookup("SYSTEM_A", "req-001", "ORGANISATION")

        assert result.context is None

    async def test_context_propagates_into_bulk_result(
        self, service: LookupService, coordinator: AsyncMock, registry_service: AsyncMock
    ) -> None:
        coordinator.lookup_by_triad.return_value = _make_decision("SRC_A", "req-001")
        registry_service.get_contexts_for_triads.return_value = {
            TriadKey("SRC_A", "req-001", "ORGANISATION"): "bulk ctx"
        }

        result = await service.handle_bulk_lookup(
            BulkLookupRequest(
                mentions=[LookupRequest(
                    identified_by=EntityMentionIdentifier(
                        source_id="SRC_A", request_id="req-001", entity_type="ORGANISATION"
                    )
                )]
            )
        )

        assert result.results[0].context == "bulk ctx"

    async def test_get_contexts_called_once_for_all_mentions(
        self, service: LookupService, coordinator: AsyncMock, registry_service: AsyncMock
    ) -> None:
        coordinator.lookup_by_triad.side_effect = [
            _make_decision("SRC_A", "req-001"),
            _make_decision("SRC_B", "req-002"),
        ]
        registry_service.get_contexts_for_triads.return_value = {}

        await service.handle_bulk_lookup(BULK_REQUEST)

        registry_service.get_contexts_for_triads.assert_awaited_once()
        identifiers_passed = registry_service.get_contexts_for_triads.call_args[0][0]
        assert len(identifiers_passed) == 2
        assert EntityMentionIdentifier(
            source_id="SRC_A", request_id="req-001", entity_type="ORGANISATION"
        ) in identifiers_passed
        assert EntityMentionIdentifier(
            source_id="SRC_B", request_id="req-002", entity_type="ORGANISATION"
        ) in identifiers_passed
