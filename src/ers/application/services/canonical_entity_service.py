from erspec.models.core import EntityMention

from ers.application.dtos import (
    CanonicalEntityPreview,
    EntityMentionPreview,
    PaginatedResult,
    PaginationParams,
)
from ers.application.exceptions import NotFoundError
from ers.application.ports.canonical_entity_repository import (
    CanonicalEntityRepository,
)
from ers.application.ports.decision_repository import DecisionRepository
from ers.application.ports.entity_mention_repository import EntityMentionRepository


class CanonicalEntityService:
    """Retrieves canonical entity previews for curation display."""

    DEFAULT_TOP_ENTITIES_LIMIT = 5

    def __init__(
        self,
        decision_repository: DecisionRepository,
        canonical_entity_repository: CanonicalEntityRepository,
        entity_mention_repository: EntityMentionRepository,
    ) -> None:
        self._decision_repository = decision_repository
        self._canonical_entity_repository = canonical_entity_repository
        self._entity_mention_repository = entity_mention_repository

    async def get_proposed_canonical_entity(
        self,
        decision_id: str,
    ) -> CanonicalEntityPreview:
        """Get the proposed (highest-confidence) canonical entity preview.

        Raises:
            NotFoundError: If the decision or canonical entity does not exist.
        """
        decision = await self._decision_repository.find_by_id(decision_id)
        if decision is None:
            raise NotFoundError("Decision", decision_id)

        return await self._build_canonical_entity_preview(
            cluster_id=decision.current_placement.cluster_id,
            confidence_score=decision.current_placement.confidence_score,
            similarity_score=decision.current_placement.similarity_score,
        )

    async def get_alternative_canonical_entities(
        self,
        decision_id: str,
        pagination: PaginationParams,
    ) -> PaginatedResult[CanonicalEntityPreview]:
        """Get alternative canonical entity previews with pagination.

        Raises:
            NotFoundError: If the decision does not exist.
        """
        decision = await self._decision_repository.find_by_id(decision_id)
        if decision is None:
            raise NotFoundError("Decision", decision_id)

        current_id = decision.current_placement.cluster_id
        alternatives = [c for c in decision.candidates if c.cluster_id != current_id]

        total = len(alternatives)
        start = (pagination.page - 1) * pagination.per_page
        page_items = alternatives[start : start + pagination.per_page]

        previews = [
            await self._build_canonical_entity_preview(
                cluster_id=candidate.cluster_id,
                confidence_score=candidate.confidence_score,
                similarity_score=candidate.similarity_score,
            )
            for candidate in page_items
        ]

        return PaginatedResult(
            count=total,
            previous=pagination.page - 1 if pagination.page > 1 else None,
            next=(pagination.page + 1 if start + pagination.per_page < total else None),
            results=previews,
        )

    async def _build_canonical_entity_preview(
        self,
        cluster_id: str,
        confidence_score: float,
        similarity_score: float,
    ) -> CanonicalEntityPreview:
        canonical_entity = await self._canonical_entity_repository.find_by_id(
            cluster_id,
        )
        if canonical_entity is None:
            raise NotFoundError("CanonicalEntity", cluster_id)

        entity_mentions = await self._entity_mention_repository.find_by_identifiers(
            identifiers=canonical_entity.equivalent_to,
            limit=self.DEFAULT_TOP_ENTITIES_LIMIT,
        )

        return CanonicalEntityPreview(
            cluster_id=cluster_id,
            confidence_score=confidence_score,
            similarity_score=similarity_score,
            top_entities=self._to_entity_mention_previews(entity_mentions),
        )

    @staticmethod
    def _to_entity_mention_previews(
        entity_mentions: list[EntityMention],
    ) -> list[EntityMentionPreview]:
        return [
            EntityMentionPreview(
                identified_by=em.identifiedBy,
                parsed_representation=em.parsed_representation,
            )
            for em in entity_mentions
        ]
