from unittest.mock import AsyncMock, create_autospec

import pytest
from erspec.models.core import EntityMention, EntityMentionIdentifier

from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.ers_rest_api.domain.errors import ErrorCode
from ers.ers_rest_api.domain.resolution import (
    BulkResolveRequest,
    EntityMentionResolutionRequest,
    EntityMentionResolutionResult,
)
from ers.ers_rest_api.services.resolve_service import ResolveService
from ers.resolution_coordinator.services.resolution_coordinator_service import (
    ResolutionCoordinatorServiceABC,
)

REQUEST = EntityMentionResolutionRequest(
    mention=EntityMention(
        identifiedBy=EntityMentionIdentifier(
            source_id="SYSTEM_A",
            request_id="req-001",
            entity_type="ORGANISATION",
        ),
        content='{"name": "Acme Corp"}',
        content_type="application/ld+json",
    ),
)


@pytest.fixture
def coordinator() -> AsyncMock:
    return create_autospec(ResolutionCoordinatorServiceABC, instance=True)


@pytest.fixture
def service(coordinator: AsyncMock) -> ResolveService:
    return ResolveService(resolution_coordinator=coordinator)


class TestResolveService:
    async def test_canonical_resolution_maps_correctly(
        self,
        service: ResolveService,
        coordinator: AsyncMock,
    ) -> None:
        coordinator.resolve.return_value = EntityMentionResolutionResult(
            identified_by=EntityMentionIdentifier(
                source_id="SYSTEM_A",
                request_id="req-001",
                entity_type="ORGANISATION",
            ),
            canonical_entity_id="cluster-010",
            status=ResolutionOutcome.CANONICAL,
        )

        result = await service.handle_resolve(REQUEST)

        assert result.canonical_entity_id == "cluster-010"
        assert result.status == ResolutionOutcome.CANONICAL
        assert result.identified_by.request_id == "req-001"

    async def test_provisional_resolution_maps_correctly(
        self,
        service: ResolveService,
        coordinator: AsyncMock,
    ) -> None:
        coordinator.resolve.return_value = EntityMentionResolutionResult(
            identified_by=EntityMentionIdentifier(
                source_id="SYSTEM_A",
                request_id="req-001",
                entity_type="ORGANISATION",
            ),
            canonical_entity_id="prov-singleton-001",
            status=ResolutionOutcome.PROVISIONAL,
        )

        result = await service.handle_resolve(REQUEST)

        assert result.canonical_entity_id == "prov-singleton-001"
        assert result.status == ResolutionOutcome.PROVISIONAL

    async def test_passes_entity_mention_to_coordinator(
        self,
        service: ResolveService,
        coordinator: AsyncMock,
    ) -> None:
        coordinator.resolve.return_value = EntityMentionResolutionResult(
            identified_by=EntityMentionIdentifier(
                source_id="SYSTEM_A",
                request_id="req-001",
                entity_type="ORGANISATION",
            ),
            canonical_entity_id="cluster-010",
            status=ResolutionOutcome.CANONICAL,
        )

        await service.handle_resolve(REQUEST)

        call_args = coordinator.resolve.call_args[0][0]
        assert call_args.identifiedBy.source_id == "SYSTEM_A"
        assert call_args.identifiedBy.request_id == "req-001"
        assert call_args.identifiedBy.entity_type == "ORGANISATION"
        assert call_args.content == '{"name": "Acme Corp"}'

    async def test_propagates_coordinator_exception(
        self,
        service: ResolveService,
        coordinator: AsyncMock,
    ) -> None:
        coordinator.resolve.side_effect = RuntimeError("coordinator unavailable")

        with pytest.raises(RuntimeError, match="coordinator unavailable"):
            await service.handle_resolve(REQUEST)


BULK_REQUEST = BulkResolveRequest(
    mentions=[
        EntityMentionResolutionRequest(
            mention=EntityMention(
                identifiedBy=EntityMentionIdentifier(
                    source_id="SRC_A",
                    request_id="req-001",
                    entity_type="ORGANISATION",
                ),
                content='{"name": "Acme"}',
                content_type="application/ld+json",
            ),
        ),
        EntityMentionResolutionRequest(
            mention=EntityMention(
                identifiedBy=EntityMentionIdentifier(
                    source_id="SRC_B",
                    request_id="req-002",
                    entity_type="ORGANISATION",
                ),
                content='{"name": "Beta"}',
                content_type="application/ld+json",
            ),
        ),
    ],
)


class TestBulkResolveService:
    async def test_all_succeed(
        self,
        service: ResolveService,
        coordinator: AsyncMock,
    ) -> None:
        coordinator.resolve.side_effect = [
            EntityMentionResolutionResult(
                identified_by=BULK_REQUEST.mentions[0].mention.identifiedBy,
                canonical_entity_id="cluster-A",
                status=ResolutionOutcome.CANONICAL,
            ),
            EntityMentionResolutionResult(
                identified_by=BULK_REQUEST.mentions[1].mention.identifiedBy,
                canonical_entity_id="cluster-B",
                status=ResolutionOutcome.PROVISIONAL,
            ),
        ]

        result = await service.handle_bulk_resolve(BULK_REQUEST)

        assert len(result.results) == 2
        assert result.results[0].canonical_entity_id == "cluster-A"
        assert result.results[1].canonical_entity_id == "cluster-B"
        assert all(r.error is None for r in result.results)

    async def test_partial_failure_collects_error(
        self,
        service: ResolveService,
        coordinator: AsyncMock,
    ) -> None:
        coordinator.resolve.side_effect = [
            EntityMentionResolutionResult(
                identified_by=BULK_REQUEST.mentions[0].mention.identifiedBy,
                canonical_entity_id="cluster-A",
                status=ResolutionOutcome.CANONICAL,
            ),
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
        self,
        service: ResolveService,
        coordinator: AsyncMock,
    ) -> None:
        coordinator.resolve.side_effect = RuntimeError("total failure")

        result = await service.handle_bulk_resolve(BULK_REQUEST)

        assert len(result.results) == 2
        assert all(r.error is not None for r in result.results)
        assert all(r.error.error_code == ErrorCode.SERVICE_ERROR for r in result.results)
