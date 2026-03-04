from erspec.models.core import Decision, EntityMention

from ers.application.dtos import (
    DecisionFilters,
    DecisionSummary,
    EntityMentionPreview,
    PaginatedResult,
    PaginationParams,
)
from ers.application.exceptions import NotFoundError
from ers.application.ports.decision_repository import DecisionRepository
from ers.application.ports.entity_mention_repository import EntityMentionRepository
from ers.application.services.user_action_service import UserActionService


class DecisionCurationService:
    """Orchestrates curation actions and decision queries."""

    def __init__(
        self,
        decision_repository: DecisionRepository,
        entity_mention_repository: EntityMentionRepository,
        user_action_service: UserActionService,
    ) -> None:
        self._decision_repository = decision_repository
        self._entity_mention_repository = entity_mention_repository
        self._user_action_service = user_action_service

    async def _get_decision_or_raise(self, decision_id: str) -> Decision:
        decision = await self._decision_repository.find_by_id(decision_id)
        if decision is None:
            raise NotFoundError("Decision", decision_id)
        return decision

    async def list_decisions(
        self,
        filters: DecisionFilters,
        pagination: PaginationParams,
    ) -> PaginatedResult[DecisionSummary]:
        """List decisions with filtering, pagination, and embedded entity data."""
        mention_identifiers = None
        if filters.search is not None:
            mention_identifiers = (
                await self._entity_mention_repository.search_identifiers(
                    filters.search,
                )
            )
            if not mention_identifiers:
                return PaginatedResult(count=0, results=[])

        paginated = await self._decision_repository.find_with_filters(
            filters=filters,
            pagination=pagination,
            mention_identifiers=mention_identifiers,
        )

        identifiers = [d.about_entity_mention for d in paginated.results]
        entity_mentions = await self._entity_mention_repository.find_by_identifiers(
            identifiers,
        )
        mention_map = self._index_by_identifier(entity_mentions)

        decision_summaries = [
            self._to_decision_summary(decision, mention_map)
            for decision in paginated.results
        ]

        return PaginatedResult(
            count=paginated.count,
            previous=paginated.previous,
            next=paginated.next,
            results=decision_summaries,
        )

    async def get_decision(self, decision_id: str) -> Decision:
        """Retrieve a single decision by ID.

        Raises:
            NotFoundError: If the decision does not exist.
        """
        return await self._get_decision_or_raise(decision_id)

    async def accept_decision(self, decision_id: str, actor: str) -> None:
        """Accept the top candidate for a decision.

        Raises:
            NotFoundError: If the decision does not exist.
            AlreadyCuratedError: If already curated on current version.
        """
        decision = await self._get_decision_or_raise(decision_id)
        await self._user_action_service.record_accept(actor=actor, decision=decision)

    async def reject_decision(self, decision_id: str, actor: str) -> None:
        """Reject all candidates for a decision.

        Raises:
            NotFoundError: If the decision does not exist.
            AlreadyCuratedError: If already curated on current version.
        """
        decision = await self._get_decision_or_raise(decision_id)
        await self._user_action_service.record_reject(actor=actor, decision=decision)

    async def assign_decision(
        self, decision_id: str, cluster_id: str, actor: str
    ) -> None:
        """Assign a decision to an alternative cluster.

        Raises:
            NotFoundError: If the decision does not exist.
            AlreadyCuratedError: If already curated on current version.
            InvalidClusterError: If cluster_id is not in candidates.
        """
        decision = await self._get_decision_or_raise(decision_id)
        await self._user_action_service.record_assign(
            actor=actor, decision=decision, cluster_id=cluster_id
        )

    @staticmethod
    def _index_by_identifier(
        entity_mentions: list[EntityMention],
    ) -> dict[tuple[str, str, str], EntityMention]:
        return {
            (
                em.identifiedBy.source_id,
                em.identifiedBy.request_id,
                em.identifiedBy.entity_type,
            ): em
            for em in entity_mentions
        }

    @staticmethod
    def _to_decision_summary(
        decision: Decision,
        mention_map: dict[tuple[str, str, str], EntityMention],
    ) -> DecisionSummary:
        emi = decision.about_entity_mention
        key = (emi.source_id, emi.request_id, emi.entity_type)
        mention = mention_map.get(key)

        return DecisionSummary(
            id=decision.id,
            about_entity_mention=EntityMentionPreview(
                identified_by=emi,
                parsed_representation=(
                    mention.parsed_representation if mention else None
                ),
            ),
            current_placement=decision.current_placement,
            created_at=decision.created_at,
            updated_at=decision.updated_at,
        )
