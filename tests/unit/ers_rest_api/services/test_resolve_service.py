from unittest.mock import AsyncMock, create_autospec

import pytest
from erspec.models.core import EntityMention, EntityMentionIdentifier

from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.ers_rest_api.domain.resolution import (
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
