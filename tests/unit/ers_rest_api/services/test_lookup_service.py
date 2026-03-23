from datetime import UTC, datetime
from unittest.mock import AsyncMock, create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers.ers_rest_api.services.exceptions import MentionNotFoundError
from ers.ers_rest_api.services.lookup_service import LookupService
from ers.resolution_decision_store.services.resolution_decision_store_service import (
    ResolutionDecisionStoreServiceABC,
)


@pytest.fixture
def decision_store() -> AsyncMock:
    return create_autospec(ResolutionDecisionStoreServiceABC, instance=True)


@pytest.fixture
def service(decision_store: AsyncMock) -> LookupService:
    return LookupService(decision_store=decision_store)


class TestLookupService:
    async def test_known_mention_returns_lookup_response(
        self,
        service: LookupService,
        decision_store: AsyncMock,
    ) -> None:
        decision_store.get_decision_for_mention.return_value = Decision(
            id="decision-001",
            about_entity_mention=EntityMentionIdentifier(
                source_id="SYSTEM_A",
                request_id="req-001",
                entity_type="ORGANISATION",
            ),
            current_placement=ClusterReference(
                cluster_id="cluster-010",
                confidence_score=0.95,
                similarity_score=0.92,
            ),
            candidates=[],
            created_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC),
            updated_at=datetime(2026, 3, 15, 11, 0, 0, tzinfo=UTC),
        )

        result = await service.handle_lookup("SYSTEM_A", "req-001", "ORGANISATION")

        assert result.cluster_reference.cluster_id == "cluster-010"
        assert result.cluster_reference.confidence_score == 0.95
        assert result.last_updated == datetime(2026, 3, 15, 11, 0, 0, tzinfo=UTC)

    async def test_uses_created_at_when_updated_at_is_none(
        self,
        service: LookupService,
        decision_store: AsyncMock,
    ) -> None:
        decision_store.get_decision_for_mention.return_value = Decision(
            id="decision-002",
            about_entity_mention=EntityMentionIdentifier(
                source_id="SYSTEM_A",
                request_id="req-002",
                entity_type="ORGANISATION",
            ),
            current_placement=ClusterReference(
                cluster_id="cluster-011",
                confidence_score=0.85,
                similarity_score=0.80,
            ),
            candidates=[],
            created_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC),
            updated_at=None,
        )

        result = await service.handle_lookup("SYSTEM_A", "req-002", "ORGANISATION")

        assert result.last_updated == datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)

    async def test_unknown_mention_raises_not_found(
        self,
        service: LookupService,
        decision_store: AsyncMock,
    ) -> None:
        decision_store.get_decision_for_mention.return_value = None

        with pytest.raises(MentionNotFoundError):
            await service.handle_lookup("SYSTEM_UNKNOWN", "req-999", "ORGANISATION")

    async def test_propagates_store_exception(
        self,
        service: LookupService,
        decision_store: AsyncMock,
    ) -> None:
        decision_store.get_decision_for_mention.side_effect = RuntimeError("store unavailable")

        with pytest.raises(RuntimeError, match="store unavailable"):
            await service.handle_lookup("SYSTEM_A", "req-001", "ORGANISATION")
