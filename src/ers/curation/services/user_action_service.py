from erspec.models.core import Decision, EntityMention, UserAction

from ers.commons.domain.data_transfer_objects import PaginatedResult, PaginationParams
from ers.curation.adapters.entity_mention_repository import (
    EntityMentionCurationRepository,
)
from ers.curation.adapters.user_action_repository import UserActionCurationRepository
from ers.curation.domain.data_transfer_objects import (
    EntityMentionPreview,
    UserActionFilters,
    UserActionSummary,
)
from ers.curation.domain.exceptions import AlreadyCuratedError
from ers.curation.domain.models import UserActionFactory


class UserActionService:
    """Creates and persists user action entries for curation commands."""

    def __init__(
        self,
        user_action_repository: UserActionCurationRepository,
        entity_mention_repository: EntityMentionCurationRepository,
    ) -> None:
        self._user_action_repository = user_action_repository
        self._entity_mention_repository = entity_mention_repository

    async def _check_not_already_curated(self, decision: Decision) -> None:
        """Raise AlreadyCuratedError if decision was already curated on its current version."""
        if decision.updated_at is not None:
            already_curated = await self._user_action_repository.has_current_action(
                about_entity_mention=decision.about_entity_mention,
                since=decision.updated_at,
            )
            if already_curated:
                raise AlreadyCuratedError(decision.id)

    async def list_user_actions(
        self,
        pagination: PaginationParams,
        filters: UserActionFilters | None = None,
    ) -> PaginatedResult[UserActionSummary]:
        """Return paginated user actions ordered by latest first."""
        paginated = await self._user_action_repository.find_paginated(pagination, filters)
        identifiers = [action.about_entity_mention for action in paginated.results]
        entity_mentions = await self._entity_mention_repository.find_by_identifiers(
            identifiers,
        )
        mention_map = self._index_by_identifier(entity_mentions)

        return PaginatedResult(
            count=paginated.count,
            previous=paginated.previous,
            next=paginated.next,
            results=[
                self._to_user_action_summary(action, mention_map) for action in paginated.results
            ],
        )

    async def record_accept(self, actor: str, decision: Decision) -> None:
        """Record an accept action in the user action trail."""
        await self._check_not_already_curated(decision)
        user_action = UserActionFactory.create_accept(actor=actor, decision=decision)
        await self._user_action_repository.save(user_action)

    async def record_reject(self, actor: str, decision: Decision) -> None:
        """Record a reject action in the user action trail."""
        await self._check_not_already_curated(decision)
        user_action = UserActionFactory.create_reject(actor=actor, decision=decision)
        await self._user_action_repository.save(user_action)

    async def record_assign(self, actor: str, decision: Decision, cluster_id: str) -> None:
        """Record an assign action in the user action trail.

        Raises:
            AlreadyCuratedError: If decision was already curated on its current version.
            InvalidClusterError: If cluster_id is not in candidates.
        """
        await self._check_not_already_curated(decision)
        user_action = UserActionFactory.create_assign(
            actor=actor, decision=decision, cluster_id=cluster_id
        )
        await self._user_action_repository.save(user_action)

    @staticmethod
    def _index_by_identifier(
        entity_mentions: list[EntityMention],
    ) -> dict[tuple[str, str, str], EntityMention]:
        return {
            (
                mention.identifiedBy.source_id,
                mention.identifiedBy.request_id,
                mention.identifiedBy.entity_type,
            ): mention
            for mention in entity_mentions
        }

    @staticmethod
    def _to_user_action_summary(
        action: UserAction,
        mention_map: dict[tuple[str, str, str], EntityMention],
    ) -> UserActionSummary:
        identifier = action.about_entity_mention
        key = (
            identifier.source_id,
            identifier.request_id,
            identifier.entity_type,
        )
        mention = mention_map.get(key)

        return UserActionSummary(
            id=action.id,
            about_entity_mention=EntityMentionPreview(
                identified_by=identifier,
                parsed_representation=(
                    mention.parsed_representation if mention is not None else None
                ),
            ),
            candidates=action.candidates,
            selected_cluster=action.selected_cluster,
            action_type=action.action_type,
            actor=action.actor,
            created_at=action.created_at,
            metadata=action.metadata,
        )
