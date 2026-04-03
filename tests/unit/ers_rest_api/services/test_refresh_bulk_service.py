from datetime import UTC, datetime
from unittest.mock import AsyncMock, create_autospec

import pytest
from erspec.models.core import (
    ClusterReference,
    Decision,
    EntityMentionIdentifier,
    LookupState,
)

from ers.ers_rest_api.domain.lookup import RefreshBulkRequest
from ers.ers_rest_api.services.refresh_bulk_service import RefreshBulkService
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.commons.domain.data_transfer_objects import CursorPage
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService


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
def decision_store() -> AsyncMock:
    return create_autospec(DecisionStoreService, instance=True)


@pytest.fixture
def registry() -> AsyncMock:
    return create_autospec(RequestRegistryService, instance=True)


@pytest.fixture
def service(decision_store: AsyncMock, registry: AsyncMock) -> RefreshBulkService:
    return RefreshBulkService(decision_store=decision_store, registry=registry)


class TestRefreshBulkService:
    async def test_returns_deltas_and_advances_snapshot(
        self,
        service: RefreshBulkService,
        decision_store: AsyncMock,
        registry: AsyncMock,
    ) -> None:
        registry.get_lookup_state.return_value = LookupState(
            source_id="SYSTEM_C",
            last_snapshot=datetime(2026, 3, 10, tzinfo=UTC),
        )
        decision_store.query_decisions_by_timestamp.return_value = CursorPage(
            results=[
                _make_decision(
                    "SYSTEM_C", "req-001", "cluster-010", datetime(2026, 3, 15, tzinfo=UTC)
                ),
                _make_decision(
                    "SYSTEM_C", "req-002", "cluster-011", datetime(2026, 3, 15, tzinfo=UTC)
                ),
            ],
            next_cursor=None,
        )

        result = await service.handle_refresh_bulk(
            RefreshBulkRequest(source_id="SYSTEM_C", limit=1000),
        )

        assert len(result.deltas) == 2
        assert result.deltas[0].cluster_reference.cluster_id == "cluster-010"
        assert result.deltas[1].identified_by.request_id == "req-002"
        assert result.has_more is False
        registry.advance_snapshot.assert_called_once()

    async def test_first_call_passes_none_snapshot(
        self,
        service: RefreshBulkService,
        decision_store: AsyncMock,
        registry: AsyncMock,
    ) -> None:
        registry.get_lookup_state.return_value = None
        decision_store.query_decisions_by_timestamp.return_value = CursorPage(
            results=[], next_cursor=None
        )

        await service.handle_refresh_bulk(
            RefreshBulkRequest(source_id="SYSTEM_NEW", limit=1000),
        )

        call_args = decision_store.query_decisions_by_timestamp.call_args
        assert call_args.kwargs["updated_since"] is None

    async def test_paginated_response_passes_cursor(
        self,
        service: RefreshBulkService,
        decision_store: AsyncMock,
        registry: AsyncMock,
    ) -> None:
        registry.get_lookup_state.return_value = LookupState(
            source_id="SYSTEM_D",
            last_snapshot=datetime(2026, 3, 10, tzinfo=UTC),
        )
        decision_store.query_decisions_by_timestamp.return_value = CursorPage(
            results=[
                _make_decision(
                    "SYSTEM_D",
                    f"req-{i:03d}",
                    f"cluster-{i:03d}",
                    datetime(2026, 3, 15, tzinfo=UTC),
                )
                for i in range(50)
            ],
            next_cursor="cursor-page-2",
        )

        result = await service.handle_refresh_bulk(
            RefreshBulkRequest(source_id="SYSTEM_D", limit=50),
        )

        assert len(result.deltas) == 50
        assert result.has_more is True
        assert result.continuation_cursor == "cursor-page-2"
        registry.advance_snapshot.assert_not_called()

    async def test_forwards_continuation_cursor_to_store(
        self,
        service: RefreshBulkService,
        decision_store: AsyncMock,
        registry: AsyncMock,
    ) -> None:
        registry.get_lookup_state.return_value = LookupState(
            source_id="SYSTEM_E",
            last_snapshot=datetime(2026, 3, 10, tzinfo=UTC),
        )
        decision_store.query_decisions_by_timestamp.return_value = CursorPage(
            results=[], next_cursor=None
        )

        await service.handle_refresh_bulk(
            RefreshBulkRequest(
                source_id="SYSTEM_E",
                limit=100,
                continuation_cursor="cursor-existing",
            ),
        )

        call_args = decision_store.query_decisions_by_timestamp.call_args
        assert call_args.kwargs["continuation_cursor"] == "cursor-existing"

    async def test_empty_delta_still_advances_snapshot(
        self,
        service: RefreshBulkService,
        decision_store: AsyncMock,
        registry: AsyncMock,
    ) -> None:
        registry.get_lookup_state.return_value = LookupState(
            source_id="SYSTEM_C",
            last_snapshot=datetime(2026, 3, 10, tzinfo=UTC),
        )
        decision_store.query_decisions_by_timestamp.return_value = CursorPage(
            results=[], next_cursor=None
        )

        result = await service.handle_refresh_bulk(
            RefreshBulkRequest(source_id="SYSTEM_C", limit=1000),
        )

        assert len(result.deltas) == 0
        registry.advance_snapshot.assert_called_once()

    async def test_snapshot_advances_on_last_page(
        self,
        service: RefreshBulkService,
        decision_store: AsyncMock,
        registry: AsyncMock,
    ) -> None:
        registry.get_lookup_state.return_value = None
        decision_store.query_decisions_by_timestamp.return_value = CursorPage(
            results=[], next_cursor=None
        )

        await service.handle_refresh_bulk(
            RefreshBulkRequest(
                source_id="SYSTEM_F",
                limit=100,
                continuation_cursor="cursor-last",
            ),
        )

        registry.advance_snapshot.assert_called_once()

    async def test_propagates_store_exception(
        self,
        service: RefreshBulkService,
        decision_store: AsyncMock,
        registry: AsyncMock,
    ) -> None:
        registry.get_lookup_state.side_effect = RuntimeError("store error")

        with pytest.raises(RuntimeError, match="store error"):
            await service.handle_refresh_bulk(
                RefreshBulkRequest(source_id="SYSTEM_H", limit=1000),
            )
