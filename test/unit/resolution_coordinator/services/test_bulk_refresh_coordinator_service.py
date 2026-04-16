"""Unit tests for BulkRefreshCoordinatorService (Spine C)."""

import inspect
from datetime import UTC, datetime
from unittest.mock import create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers.commons.domain.data_transfer_objects import CursorPage
from ers.request_registry.domain.records import LookupRequestRecord
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_coordinator.domain.exceptions import SourceNotFoundError
from ers.resolution_coordinator.services.bulk_refresh_coordinator_service import (
    BulkRefreshCoordinatorService,
)
from ers.resolution_decision_store.domain.errors import RepositoryConnectionError
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService


def _make_decision() -> Decision:
    now = datetime.now(UTC)
    identifier = EntityMentionIdentifier(
        source_id="SRC_A", request_id="req1", entity_type="Person"
    )
    cluster = ClusterReference(cluster_id="c1", confidence_score=0.9, similarity_score=0.85)
    return Decision(
        id="hash123",
        about_entity_mention=identifier,
        current_placement=cluster,
        candidates=[],
        created_at=now,
        updated_at=now,
    )


def _lookup_state(t: datetime) -> LookupRequestRecord:
    return LookupRequestRecord(source_id="SRC_A", last_snapshot=t, updated_at=t)


@pytest.fixture
def registry_svc():
    mock = create_autospec(RequestRegistryService, instance=True)
    mock.source_has_requests.return_value = True
    mock.get_lookup_state.return_value = None
    mock.advance_snapshot.return_value = None
    return mock


@pytest.fixture
def decision_svc():
    mock = create_autospec(DecisionStoreService, instance=True)
    mock.query_decisions_delta.return_value = CursorPage(results=[], next_cursor=None)
    return mock


class TestRefreshBulk:
    async def test_returns_delta_with_prior_snapshot(self, registry_svc, decision_svc):
        t0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        registry_svc.get_lookup_state.return_value = _lookup_state(t0)
        expected_page = CursorPage(results=[_make_decision()], next_cursor=None)
        decision_svc.query_decisions_delta.return_value = expected_page
        svc = BulkRefreshCoordinatorService(registry_svc, decision_svc)

        result = await svc.refresh_bulk("SRC_A")

        decision_svc.query_decisions_delta.assert_awaited_once()
        call_kwargs = decision_svc.query_decisions_delta.call_args.kwargs
        assert call_kwargs["updated_since"] == t0
        registry_svc.advance_snapshot.assert_awaited_once()
        assert result is expected_page

    async def test_returns_all_on_first_lookup(self, registry_svc, decision_svc):
        registry_svc.get_lookup_state.return_value = None
        svc = BulkRefreshCoordinatorService(registry_svc, decision_svc)

        await svc.refresh_bulk("SRC_A")

        call_kwargs = decision_svc.query_decisions_delta.call_args.kwargs
        assert call_kwargs["updated_since"] is None

    async def test_empty_delta_still_advances_snapshot(self, registry_svc, decision_svc):
        empty_page = CursorPage(results=[], next_cursor=None)
        decision_svc.query_decisions_delta.return_value = empty_page
        svc = BulkRefreshCoordinatorService(registry_svc, decision_svc)

        result = await svc.refresh_bulk("SRC_A")

        registry_svc.advance_snapshot.assert_awaited_once()
        assert result is empty_page

    async def test_unknown_source_raises(self, registry_svc, decision_svc):
        registry_svc.source_has_requests.return_value = False
        svc = BulkRefreshCoordinatorService(registry_svc, decision_svc)

        with pytest.raises(SourceNotFoundError) as exc_info:
            await svc.refresh_bulk("UNKNOWN")

        assert exc_info.value.source_id == "UNKNOWN"
        decision_svc.query_decisions_delta.assert_not_awaited()

    async def test_decision_store_unavailable(self, registry_svc, decision_svc):
        decision_svc.query_decisions_delta.side_effect = RepositoryConnectionError("MongoDB down")
        svc = BulkRefreshCoordinatorService(registry_svc, decision_svc)

        with pytest.raises(RepositoryConnectionError):
            await svc.refresh_bulk("SRC_A")

        registry_svc.advance_snapshot.assert_not_awaited()

    def test_read_only_no_publish(self):
        """EREPublishService must not be a constructor dependency."""
        from ers.ere_contract_client.services.ere_publish_service import EREPublishService

        annotations = [
            p.annotation
            for p in inspect.signature(BulkRefreshCoordinatorService.__init__).parameters.values()
            if p.name != "self"
        ]
        assert EREPublishService not in annotations

    def test_read_only_no_store_decision(self):
        """No store_decision write adapter should be injected in the constructor."""
        param_names = [
            name
            for name in inspect.signature(
                BulkRefreshCoordinatorService.__init__
            ).parameters
            if name != "self"
        ]
        assert "store_decision" not in param_names

    async def test_snapshot_advanced_after_delta(self, registry_svc, decision_svc):
        svc = BulkRefreshCoordinatorService(registry_svc, decision_svc)
        call_order = []

        async def track_delta(**kwargs):
            call_order.append("delta")
            return CursorPage(results=[], next_cursor=None)

        async def track_snapshot(*args, **kwargs):
            call_order.append("snapshot")

        decision_svc.query_decisions_delta.side_effect = track_delta
        registry_svc.advance_snapshot.side_effect = track_snapshot

        await svc.refresh_bulk("SRC_A")

        assert call_order == ["delta", "snapshot"]

    async def test_cursor_and_page_size_forwarded(self, registry_svc, decision_svc):
        svc = BulkRefreshCoordinatorService(registry_svc, decision_svc)

        await svc.refresh_bulk("SRC_A", cursor="tok", page_size=50)

        call_kwargs = decision_svc.query_decisions_delta.call_args.kwargs
        assert call_kwargs["cursor"] == "tok"
        assert call_kwargs["page_size"] == 50

    async def test_returns_page_unchanged(self, registry_svc, decision_svc):
        decisions = [_make_decision() for _ in range(3)]
        expected_page = CursorPage(results=decisions, next_cursor="next-tok")
        decision_svc.query_decisions_delta.return_value = expected_page
        svc = BulkRefreshCoordinatorService(registry_svc, decision_svc)

        result = await svc.refresh_bulk("SRC_A")

        assert result is expected_page
        assert len(result.results) == 3
        assert result.next_cursor == "next-tok"

    async def test_snapshot_not_advanced_mid_pagination(self, registry_svc, decision_svc):
        """Snapshot must NOT advance when next_cursor is set — pagination is incomplete."""
        mid_page = CursorPage(results=[_make_decision()], next_cursor="tok2")
        decision_svc.query_decisions_delta.return_value = mid_page
        svc = BulkRefreshCoordinatorService(registry_svc, decision_svc)

        await svc.refresh_bulk("SRC_A")

        registry_svc.advance_snapshot.assert_not_awaited()
