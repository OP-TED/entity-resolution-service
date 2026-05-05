"""Unit tests for ResolveService — Decision→EntityMentionResolutionResult mapping."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, create_autospec

import pytest
from erspec.models.core import (
    ClusterReference,
    Decision,
    EntityMention,
    EntityMentionIdentifier,
)

from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.ers_rest_api.domain.errors import ErrorCode
from ers.ers_rest_api.domain.resolution import (
    BulkResolveRequest,
    EntityMentionResolutionRequest,
)
from ers.ers_rest_api.services.resolve_service import ResolveService
from ers.resolution_coordinator.services.resolution_coordinator_service import (
    ResolutionCoordinatorService,
)

IDENT = EntityMentionIdentifier(
    source_id="SYSTEM_A", request_id="req-001", entity_type="ORGANISATION"
)

REQUEST = EntityMentionResolutionRequest(
    mention=EntityMention(
        identifiedBy=IDENT,
        content='{"name": "Acme Corp"}',
        content_type="application/ld+json",
    ),
)


def _make_decision(
    identifier: EntityMentionIdentifier, cluster_id: str
) -> Decision:
    now = datetime.now(UTC)
    return Decision(
        id=f"decision-{identifier.request_id}",
        about_entity_mention=identifier,
        current_placement=ClusterReference(
            cluster_id=cluster_id,
            confidence_score=0.9,
            similarity_score=0.85,
        ),
        candidates=[],
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def coordinator() -> AsyncMock:
    return create_autospec(ResolutionCoordinatorService, instance=True)


@pytest.fixture
def service(coordinator: AsyncMock) -> ResolveService:
    return ResolveService(resolution_coordinator=coordinator)


class TestResolveService:
    async def test_canonical_resolution_maps_correctly(
        self, service: ResolveService, coordinator: AsyncMock
    ) -> None:
        coordinator.resolve_single.return_value = (
            _make_decision(IDENT, "cluster-010"), ResolutionOutcome.CANONICAL
        )

        result = await service.handle_resolve(REQUEST)

        assert result.canonical_entity_id == "cluster-010"
        assert result.status == ResolutionOutcome.CANONICAL
        assert result.identified_by == IDENT

    async def test_provisional_resolution_maps_correctly(
        self, service: ResolveService, coordinator: AsyncMock
    ) -> None:
        coordinator.resolve_single.return_value = (
            _make_decision(IDENT, "prov-hash-xyz"), ResolutionOutcome.PROVISIONAL
        )

        result = await service.handle_resolve(REQUEST)

        assert result.canonical_entity_id == "prov-hash-xyz"
        assert result.status == ResolutionOutcome.PROVISIONAL

    async def test_passes_entity_mention_to_coordinator(
        self, service: ResolveService, coordinator: AsyncMock
    ) -> None:
        coordinator.resolve_single.return_value = (
            _make_decision(IDENT, "cluster-010"), ResolutionOutcome.CANONICAL
        )

        await service.handle_resolve(REQUEST)

        call_args = coordinator.resolve_single.call_args[0][0]
        assert call_args.identifiedBy.source_id == "SYSTEM_A"
        assert call_args.identifiedBy.request_id == "req-001"
        assert call_args.content == '{"name": "Acme Corp"}'

    async def test_propagates_coordinator_exception(
        self, service: ResolveService, coordinator: AsyncMock
    ) -> None:
        coordinator.resolve_single.side_effect = RuntimeError("coordinator unavailable")

        with pytest.raises(RuntimeError, match="coordinator unavailable"):
            await service.handle_resolve(REQUEST)


IDENT_A = EntityMentionIdentifier(
    source_id="SRC_A", request_id="req-001", entity_type="ORGANISATION"
)
IDENT_B = EntityMentionIdentifier(
    source_id="SRC_B", request_id="req-002", entity_type="ORGANISATION"
)

BULK_REQUEST = BulkResolveRequest(
    mentions=[
        EntityMentionResolutionRequest(
            mention=EntityMention(
                identifiedBy=IDENT_A,
                content='{"name": "Acme"}',
                content_type="application/ld+json",
            ),
        ),
        EntityMentionResolutionRequest(
            mention=EntityMention(
                identifiedBy=IDENT_B,
                content='{"name": "Beta"}',
                content_type="application/ld+json",
            ),
        ),
    ],
)


class TestBulkResolveService:
    async def test_all_succeed(
        self, service: ResolveService, coordinator: AsyncMock
    ) -> None:
        coordinator.resolve_bulk.return_value = [
            (_make_decision(IDENT_A, "cluster-A"), ResolutionOutcome.CANONICAL),
            (_make_decision(IDENT_B, "cluster-B"), ResolutionOutcome.CANONICAL),
        ]

        result = await service.handle_bulk_resolve(BULK_REQUEST)

        assert len(result.results) == 2
        assert result.results[0].canonical_entity_id == "cluster-A"
        assert result.results[1].canonical_entity_id == "cluster-B"
        assert all(r.error is None for r in result.results)

    async def test_partial_failure_collects_error(
        self, service: ResolveService, coordinator: AsyncMock
    ) -> None:
        coordinator.resolve_bulk.return_value = [
            (_make_decision(IDENT_A, "cluster-A"), ResolutionOutcome.CANONICAL),
            RuntimeError("coordinator down"),
        ]

        result = await service.handle_bulk_resolve(BULK_REQUEST)

        assert len(result.results) == 2
        assert result.results[0].canonical_entity_id == "cluster-A"
        assert result.results[0].error is None
        assert result.results[1].error is not None
        assert result.results[1].error.error_code == ErrorCode.SERVICE_ERROR
        assert result.results[1].canonical_entity_id is None

    async def test_all_fail_collects_errors(
        self, service: ResolveService, coordinator: AsyncMock
    ) -> None:
        coordinator.resolve_bulk.return_value = [
            RuntimeError("total failure"),
            RuntimeError("total failure"),
        ]

        result = await service.handle_bulk_resolve(BULK_REQUEST)

        assert len(result.results) == 2
        assert all(r.error is not None for r in result.results)
        assert all(r.error.error_code == ErrorCode.SERVICE_ERROR for r in result.results)

    async def test_uses_resolve_bulk_not_sequential(
        self, service: ResolveService, coordinator: AsyncMock
    ) -> None:
        """Verify bulk uses coordinator.resolve_bulk, not sequential resolve_single."""
        coordinator.resolve_bulk.return_value = [
            (_make_decision(IDENT_A, "cluster-A"), ResolutionOutcome.CANONICAL),
            (_make_decision(IDENT_B, "cluster-B"), ResolutionOutcome.CANONICAL),
        ]

        await service.handle_bulk_resolve(BULK_REQUEST)

        coordinator.resolve_bulk.assert_awaited_once()
        coordinator.resolve_single.assert_not_called()

    async def test_service_unavailable_maps_to_service_unavailable_code(
        self, service: ResolveService, coordinator: AsyncMock
    ) -> None:
        """C2: ServiceUnavailableError on a bulk item must surface as
        ``SERVICE_UNAVAILABLE``, not the generic ``SERVICE_ERROR``.

        Per the (a) decision (2026-05-05), infrastructure outages on the
        resolve path are visible to the caller as 503 — and for bulk
        endpoints, the per-item error code must reflect that contract so
        clients can distinguish a backend outage from an arbitrary failure.
        """
        from ers.commons.services.exceptions import ServiceUnavailableError

        coordinator.resolve_bulk.return_value = [
            (_make_decision(IDENT_A, "cluster-A"), ResolutionOutcome.CANONICAL),
            ServiceUnavailableError("redis", "Redis down"),
        ]

        result = await service.handle_bulk_resolve(BULK_REQUEST)

        assert len(result.results) == 2
        assert result.results[0].error is None
        assert result.results[1].error is not None
        assert result.results[1].error.error_code == ErrorCode.SERVICE_UNAVAILABLE
        assert result.results[1].canonical_entity_id is None
