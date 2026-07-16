"""Unit tests for RefreshBulkService — BulkRefreshCoordinatorService delegation."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, create_autospec

import pytest
from erspec.models.core import (
    ClusterReference,
    Decision,
    EntityMentionIdentifier,
)

from ers.commons.domain.data_transfer_objects import CursorPage
from ers.ers_rest_api.domain.lookup import RefreshBulkRequest
from ers.ers_rest_api.services.refresh_bulk_service import RefreshBulkService
from ers.request_registry.domain.records import TriadKey
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_coordinator.services.bulk_refresh_coordinator_service import (
    BulkRefreshCoordinatorService,
)


def _make_decision(
    source_id: str, request_id: str, cluster_id: str, updated_at: datetime
) -> Decision:
    return Decision(
        id=f"decision-{request_id}",
        about_entity_mention=EntityMentionIdentifier(
            source_id=source_id,
            request_id=request_id,
            entity_type="ORGANISATION",
        ),
        current_placement=ClusterReference(
            cluster_id=cluster_id,
            confidence_score=0.9,
            similarity_score=0.85,
        ),
        candidates=[],
        created_at=datetime(2026, 3, 1, tzinfo=UTC),
        updated_at=updated_at,
    )


@pytest.fixture
def bulk_coordinator() -> AsyncMock:
    return create_autospec(BulkRefreshCoordinatorService, instance=True)


@pytest.fixture
def registry_service() -> AsyncMock:
    mock = create_autospec(RequestRegistryService, instance=True)
    mock.get_contexts_for_triads.return_value = {}
    return mock


@pytest.fixture
def service(bulk_coordinator: AsyncMock, registry_service: AsyncMock) -> RefreshBulkService:
    return RefreshBulkService(
        bulk_coordinator=bulk_coordinator,
        registry_service=registry_service,
    )


class TestRefreshBulkService:
    async def test_returns_deltas(
        self, service: RefreshBulkService, bulk_coordinator: AsyncMock
    ) -> None:
        bulk_coordinator.refresh_bulk.return_value = CursorPage(
            results=[
                _make_decision("SYSTEM_C", "req-001", "cluster-010", datetime(2026, 3, 15, tzinfo=UTC)),
                _make_decision("SYSTEM_C", "req-002", "cluster-011", datetime(2026, 3, 15, tzinfo=UTC)),
            ],
            count=2,
            next_cursor=None,
        )

        result = await service.handle_refresh_bulk(
            RefreshBulkRequest(source_id="SYSTEM_C", limit=1000),
        )

        assert len(result.deltas) == 2
        assert result.deltas[0].cluster_reference.cluster_id == "cluster-010"
        assert result.deltas[1].identified_by.request_id == "req-002"
        assert result.has_more is False

    async def test_first_call_passes_none_cursor(
        self, service: RefreshBulkService, bulk_coordinator: AsyncMock
    ) -> None:
        bulk_coordinator.refresh_bulk.return_value = CursorPage(
            results=[], count=0, next_cursor=None
        )

        await service.handle_refresh_bulk(
            RefreshBulkRequest(source_id="SYSTEM_NEW", limit=1000),
        )

        call_args = bulk_coordinator.refresh_bulk.call_args
        assert call_args.kwargs["cursor"] is None

    async def test_paginated_response_passes_cursor(
        self, service: RefreshBulkService, bulk_coordinator: AsyncMock
    ) -> None:
        bulk_coordinator.refresh_bulk.return_value = CursorPage(
            results=[
                _make_decision(
                    "SYSTEM_D", f"req-{i:03d}", f"cluster-{i:03d}",
                    datetime(2026, 3, 15, tzinfo=UTC),
                )
                for i in range(50)
            ],
            count=50,
            next_cursor="cursor-page-2",
        )

        result = await service.handle_refresh_bulk(
            RefreshBulkRequest(source_id="SYSTEM_D", limit=50),
        )

        assert len(result.deltas) == 50
        assert result.has_more is True
        assert result.continuation_cursor == "cursor-page-2"

    async def test_forwards_continuation_cursor_to_coordinator(
        self, service: RefreshBulkService, bulk_coordinator: AsyncMock
    ) -> None:
        bulk_coordinator.refresh_bulk.return_value = CursorPage(
            results=[], count=0, next_cursor=None
        )

        await service.handle_refresh_bulk(
            RefreshBulkRequest(
                source_id="SYSTEM_E",
                limit=100,
                continuation_cursor="cursor-existing",
            ),
        )

        call_args = bulk_coordinator.refresh_bulk.call_args
        assert call_args.kwargs["cursor"] == "cursor-existing"

    async def test_empty_delta(
        self, service: RefreshBulkService, bulk_coordinator: AsyncMock
    ) -> None:
        bulk_coordinator.refresh_bulk.return_value = CursorPage(
            results=[], count=0, next_cursor=None
        )

        result = await service.handle_refresh_bulk(
            RefreshBulkRequest(source_id="SYSTEM_C", limit=1000),
        )

        assert len(result.deltas) == 0
        assert result.has_more is False

    async def test_propagates_coordinator_exception(
        self, service: RefreshBulkService, bulk_coordinator: AsyncMock
    ) -> None:
        bulk_coordinator.refresh_bulk.side_effect = RuntimeError("store error")

        with pytest.raises(RuntimeError, match="store error"):
            await service.handle_refresh_bulk(
                RefreshBulkRequest(source_id="SYSTEM_H", limit=1000),
            )


class TestRefreshBulkServiceContext:
    async def test_context_in_delta_when_registry_returns_it(
        self,
        service: RefreshBulkService,
        bulk_coordinator: AsyncMock,
        registry_service: AsyncMock,
    ) -> None:
        decision = _make_decision(
            "SYSTEM_C", "req-001", "cluster-010", datetime(2026, 3, 15, tzinfo=UTC)
        )
        bulk_coordinator.refresh_bulk.return_value = CursorPage(
            results=[decision], count=1, next_cursor=None
        )
        registry_service.get_contexts_for_triads.return_value = {
            TriadKey("SYSTEM_C", "req-001", "ORGANISATION"): "procurement ctx"
        }

        result = await service.handle_refresh_bulk(
            RefreshBulkRequest(source_id="SYSTEM_C", limit=1000)
        )

        assert result.deltas[0].context == "procurement ctx"

    async def test_context_is_none_when_triad_not_in_registry(
        self,
        service: RefreshBulkService,
        bulk_coordinator: AsyncMock,
        registry_service: AsyncMock,
    ) -> None:
        decision = _make_decision(
            "SYSTEM_C", "req-001", "cluster-010", datetime(2026, 3, 15, tzinfo=UTC)
        )
        bulk_coordinator.refresh_bulk.return_value = CursorPage(
            results=[decision], count=1, next_cursor=None
        )
        registry_service.get_contexts_for_triads.return_value = {}

        result = await service.handle_refresh_bulk(
            RefreshBulkRequest(source_id="SYSTEM_C", limit=1000)
        )

        assert result.deltas[0].context is None

    async def test_get_contexts_called_with_decision_identifiers(
        self,
        service: RefreshBulkService,
        bulk_coordinator: AsyncMock,
        registry_service: AsyncMock,
    ) -> None:
        decision = _make_decision(
            "SYSTEM_C", "req-001", "cluster-010", datetime(2026, 3, 15, tzinfo=UTC)
        )
        bulk_coordinator.refresh_bulk.return_value = CursorPage(
            results=[decision], count=1, next_cursor=None
        )

        await service.handle_refresh_bulk(RefreshBulkRequest(source_id="SYSTEM_C", limit=1000))

        identifiers_passed = registry_service.get_contexts_for_triads.call_args[0][0]
        assert decision.about_entity_mention in identifiers_passed

    async def test_empty_delta_calls_registry_with_empty_list(
        self,
        service: RefreshBulkService,
        bulk_coordinator: AsyncMock,
        registry_service: AsyncMock,
    ) -> None:
        bulk_coordinator.refresh_bulk.return_value = CursorPage(
            results=[], count=0, next_cursor=None
        )

        await service.handle_refresh_bulk(RefreshBulkRequest(source_id="SYSTEM_C", limit=1000))

        registry_service.get_contexts_for_triads.assert_awaited_once_with([])
