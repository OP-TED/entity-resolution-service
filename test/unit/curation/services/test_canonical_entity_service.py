from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest

from ers.commons.domain.data_transfer_objects import PaginatedResult, PaginationParams
from ers.commons.services.exceptions import NotFoundError
from ers.curation.adapters import (
    EntityMentionCurationRepository,
)
from ers.curation.domain.data_transfer_objects import CanonicalEntityPreview
from ers.curation.services import CanonicalEntityService
from ers.resolution_decision_store.adapters.decision_repository import DecisionRepository
from ers.resolution_decision_store.domain.cluster_size_index import ClusterSizeIndex
from test.unit.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
    EntityMentionFactory,
    EntityMentionIdentifierFactory,
)


@pytest.fixture
def decision_repository() -> MagicMock:
    return create_autospec(DecisionRepository, instance=True)


@pytest.fixture
def entity_mention_repository() -> MagicMock:
    return create_autospec(EntityMentionCurationRepository, instance=True)


@pytest.fixture
def cluster_size_index() -> AsyncMock:
    mock = create_autospec(ClusterSizeIndex, instance=True)
    mock.get_size.return_value = 0
    return mock


@pytest.fixture
def service(
    decision_repository: MagicMock,
    entity_mention_repository: MagicMock,
    cluster_size_index: AsyncMock,
) -> CanonicalEntityService:
    return CanonicalEntityService(
        decision_repository=decision_repository,
        entity_mention_repository=entity_mention_repository,
        cluster_size_index=cluster_size_index,
    )


@pytest.fixture
def service_without_index(
    decision_repository: MagicMock,
    entity_mention_repository: MagicMock,
) -> CanonicalEntityService:
    """Service with no cluster_size_index — tests the default=None path."""
    return CanonicalEntityService(
        decision_repository=decision_repository,
        entity_mention_repository=entity_mention_repository,
    )


class TestGetProposedCanonicalEntity:
    async def test_returns_preview_with_embedded_entities(
        self,
        service: CanonicalEntityService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        member_ids = EntityMentionIdentifierFactory.batch(3)
        decision = DecisionFactory.build()
        mentions = [EntityMentionFactory.build(identifiedBy=mid) for mid in member_ids]

        decision_repository.find_by_id.return_value = decision
        decision_repository.find_mention_ids_by_cluster.return_value = member_ids
        entity_mention_repository.find_by_identifiers.return_value = mentions

        result = await service.get_proposed_canonical_entity(decision.id)

        assert isinstance(result, CanonicalEntityPreview)
        assert result.cluster_id == decision.current_placement.cluster_id
        assert result.confidence_score == decision.current_placement.confidence_score
        assert result.similarity_score == decision.current_placement.similarity_score
        assert len(result.top_entities) == 3
        decision_repository.find_mention_ids_by_cluster.assert_called_once_with(
            decision.current_placement.cluster_id,
            limit=service.DEFAULT_TOP_ENTITIES_LIMIT,
        )

    async def test_decision_not_found_raises_error(
        self,
        service: CanonicalEntityService,
        decision_repository: MagicMock,
    ) -> None:
        decision_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError) as exc_info:
            await service.get_proposed_canonical_entity("nonexistent")

        assert exc_info.value.entity_type == "Decision"

    async def test_empty_cluster_returns_preview_with_no_entities(
        self,
        service: CanonicalEntityService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        decision_repository.find_by_id.return_value = decision
        decision_repository.find_mention_ids_by_cluster.return_value = []
        entity_mention_repository.find_by_identifiers.return_value = []

        result = await service.get_proposed_canonical_entity(decision.id)

        assert result.top_entities == []


class TestGetAlternativeCanonicalEntities:
    async def test_returns_paginated_alternatives(
        self,
        service: CanonicalEntityService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        current = ClusterReferenceFactory.build(confidence_score=0.9, similarity_score=0.85)
        alt1 = ClusterReferenceFactory.build(confidence_score=0.7, similarity_score=0.65)
        alt2 = ClusterReferenceFactory.build(confidence_score=0.5, similarity_score=0.45)
        decision = DecisionFactory.build(
            current_placement=current,
            candidates=[current, alt1, alt2],
        )
        decision_repository.find_by_id.return_value = decision
        decision_repository.find_mention_ids_by_cluster.return_value = (
            EntityMentionIdentifierFactory.batch(2)
        )
        entity_mention_repository.find_by_identifiers.return_value = EntityMentionFactory.batch(2)

        result = await service.get_alternative_canonical_entities(
            decision.id,
            pagination=PaginationParams(page=1, per_page=10),
        )

        assert isinstance(result, PaginatedResult)
        assert result.count == 2
        assert len(result.results) == 2
        assert result.next is None
        assert result.previous is None

    async def test_excludes_current_placement(
        self,
        service: CanonicalEntityService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        current = ClusterReferenceFactory.build(confidence_score=0.9, similarity_score=0.85)
        alt = ClusterReferenceFactory.build(confidence_score=0.6, similarity_score=0.55)
        decision = DecisionFactory.build(
            current_placement=current,
            candidates=[current, alt],
        )
        decision_repository.find_by_id.return_value = decision
        decision_repository.find_mention_ids_by_cluster.return_value = (
            EntityMentionIdentifierFactory.batch(2)
        )
        entity_mention_repository.find_by_identifiers.return_value = EntityMentionFactory.batch(2)

        result = await service.get_alternative_canonical_entities(
            decision.id,
            pagination=PaginationParams(page=1, per_page=10),
        )

        assert result.count == 1
        assert result.results[0].cluster_id == alt.cluster_id

    async def test_pagination_returns_correct_page(
        self,
        service: CanonicalEntityService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        current = ClusterReferenceFactory.build(confidence_score=0.95, similarity_score=0.9)
        alternatives = ClusterReferenceFactory.batch(5)
        decision = DecisionFactory.build(
            current_placement=current,
            candidates=[current, *alternatives],
        )
        decision_repository.find_by_id.return_value = decision
        decision_repository.find_mention_ids_by_cluster.return_value = (
            EntityMentionIdentifierFactory.batch(2)
        )
        entity_mention_repository.find_by_identifiers.return_value = EntityMentionFactory.batch(2)

        result = await service.get_alternative_canonical_entities(
            decision.id,
            pagination=PaginationParams(page=1, per_page=2),
        )

        assert result.count == 5
        assert len(result.results) == 2
        assert result.next == 2
        assert result.previous is None

    async def test_decision_not_found_raises_error(
        self,
        service: CanonicalEntityService,
        decision_repository: MagicMock,
    ) -> None:
        decision_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.get_alternative_canonical_entities(
                "nonexistent",
                pagination=PaginationParams(),
            )


class TestBuildClusterPreviewWithClusterSizeIndex:
    """build_cluster_preview reads cluster_size from ClusterSizeIndex, not decisions collection."""

    async def test_cluster_size_populated_from_index(
        self,
        service: CanonicalEntityService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        cluster_size_index: AsyncMock,
    ) -> None:
        cluster_id = "cluster-abc"
        cluster_size_index.get_size.return_value = 7
        decision_repository.find_mention_ids_by_cluster.return_value = []
        entity_mention_repository.find_by_identifiers.return_value = []

        result = await service.build_cluster_preview(
            cluster_id=cluster_id,
            confidence_score=0.9,
            similarity_score=0.8,
        )

        assert result.cluster_size == 7
        cluster_size_index.get_size.assert_called_once_with(cluster_id)

    async def test_cluster_size_zero_when_cluster_unknown(
        self,
        service: CanonicalEntityService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        cluster_size_index: AsyncMock,
    ) -> None:
        cluster_size_index.get_size.return_value = 0
        decision_repository.find_mention_ids_by_cluster.return_value = []
        entity_mention_repository.find_by_identifiers.return_value = []

        result = await service.build_cluster_preview(
            cluster_id="unknown-cluster",
            confidence_score=0.5,
            similarity_score=0.4,
        )

        assert result.cluster_size == 0

    async def test_no_count_documents_call_on_decisions(
        self,
        service: CanonicalEntityService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        cluster_size_index: AsyncMock,
    ) -> None:
        """build_cluster_preview must NOT call count_documents on the decision repo."""
        cluster_size_index.get_size.return_value = 3
        decision_repository.find_mention_ids_by_cluster.return_value = []
        entity_mention_repository.find_by_identifiers.return_value = []

        await service.build_cluster_preview(
            cluster_id="any-cluster",
            confidence_score=0.7,
            similarity_score=0.6,
        )

        assert not hasattr(decision_repository, "count_documents") or (
            not decision_repository.count_documents.called
        )

    async def test_cluster_size_zero_when_index_not_injected(
        self,
        service_without_index: CanonicalEntityService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        """When no ClusterSizeIndex is injected cluster_size defaults to 0."""
        decision_repository.find_mention_ids_by_cluster.return_value = []
        entity_mention_repository.find_by_identifiers.return_value = []

        result = await service_without_index.build_cluster_preview(
            cluster_id="any-cluster",
            confidence_score=0.5,
            similarity_score=0.4,
        )

        assert result.cluster_size == 0


class TestGetProposedCanonicalEntityWithClusterSize:
    """get_proposed_canonical_entity propagates cluster_size from build_cluster_preview."""

    async def test_proposed_entity_carries_cluster_size(
        self,
        service: CanonicalEntityService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        cluster_size_index: AsyncMock,
    ) -> None:
        decision = DecisionFactory.build()
        cluster_size_index.get_size.return_value = 11
        decision_repository.find_by_id.return_value = decision
        decision_repository.find_mention_ids_by_cluster.return_value = []
        entity_mention_repository.find_by_identifiers.return_value = []

        result = await service.get_proposed_canonical_entity(decision.id)

        assert result.cluster_size == 11


class TestGetAlternativeCanonicalEntitiesWithClusterSize:
    """get_alternative_canonical_entities propagates cluster_size for each alternative."""

    async def test_alternatives_each_carry_cluster_size(
        self,
        service: CanonicalEntityService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        cluster_size_index: AsyncMock,
    ) -> None:
        current = ClusterReferenceFactory.build(confidence_score=0.9, similarity_score=0.85)
        alt1 = ClusterReferenceFactory.build(confidence_score=0.7, similarity_score=0.65)
        alt2 = ClusterReferenceFactory.build(confidence_score=0.5, similarity_score=0.45)
        decision = DecisionFactory.build(
            current_placement=current,
            candidates=[current, alt1, alt2],
        )
        decision_repository.find_by_id.return_value = decision
        decision_repository.find_mention_ids_by_cluster.return_value = []
        entity_mention_repository.find_by_identifiers.return_value = []
        # Return distinct sizes for different clusters
        cluster_size_index.get_size.side_effect = lambda cid: (
            4 if cid == alt1.cluster_id else 11
        )

        result = await service.get_alternative_canonical_entities(
            decision.id,
            pagination=PaginationParams(page=1, per_page=10),
        )

        assert len(result.results) == 2
        sizes = {r.cluster_id: r.cluster_size for r in result.results}
        assert sizes[alt1.cluster_id] == 4
        assert sizes[alt2.cluster_id] == 11
