from erspec.models.core import EntityMention

from ers.commons.domain.data_transfer_objects import PaginatedResult, PaginationParams
from ers.commons.services.exceptions import NotFoundError
from ers.curation.adapters import (
    DecisionCurationRepository,
    EntityMentionCurationRepository,
)
from ers.curation.domain.data_transfer_objects import (
    CanonicalEntityPreview,
    EntityMentionPreview,
)


class CanonicalEntityService:
    """Retrieves canonical entity previews for curation display."""

    DEFAULT_TOP_ENTITIES_LIMIT = 5

    def __init__(
        self,
        decision_repository: DecisionCurationRepository,
        entity_mention_repository: EntityMentionCurationRepository,
    ) -> None:
        self._decision_repository = decision_repository
        self._entity_mention_repository = entity_mention_repository

    async def get_proposed_canonical_entity(
        self,
        decision_id: str,
    ) -> CanonicalEntityPreview:
        """Get the proposed (highest-confidence) canonical entity preview.

        Raises:
            NotFoundError: If the decision does not exist.
        """
        decision = await self._decision_repository.find_by_id(decision_id)
        if decision is None:
            raise NotFoundError("Decision", decision_id)

        return await self.build_cluster_preview(
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
        alternatives.sort(key=lambda c: c.confidence_score, reverse=True)

        total = len(alternatives)
        start = (pagination.page - 1) * pagination.per_page
        page_items = alternatives[start : start + pagination.per_page]

        previews = [
            await self.build_cluster_preview(
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

    async def build_cluster_preview(
        self,
        cluster_id: str,
        confidence_score: float,
        similarity_score: float,
    ) -> CanonicalEntityPreview:
        mention_ids = await self._decision_repository.find_mention_ids_by_cluster(
            cluster_id,
            limit=self.DEFAULT_TOP_ENTITIES_LIMIT,
        )

        entity_mentions = await self._entity_mention_repository.find_by_identifiers(
            identifiers=mention_ids,
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
