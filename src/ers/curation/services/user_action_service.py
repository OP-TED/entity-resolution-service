from erspec.models.core import Decision, EntityMention, UserAction

from ers.commons.domain.data_transfer_objects import (
    CursorPage,
    CursorParams,
    PaginatedResult,
    PaginationParams,
)
from ers.commons.services.exceptions import NotFoundError
from ers.curation.adapters.entity_mention_repository import (
    EntityMentionCurationRepository,
)
from ers.curation.adapters.user_action_repository import UserActionCurationRepository
from ers.curation.domain.data_transfer_objects import (
    CanonicalEntityPreview,
    EntityMentionPreview,
    UserActionFilters,
    UserActionSummary,
)
from ers.curation.domain.exceptions import AlreadyCuratedError
from ers.curation.domain.models import UserActionFactory
from ers.curation.services.canonical_entity_service import CanonicalEntityService


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
        cursor_params: CursorParams,
        filters: UserActionFilters | None = None,
    ) -> CursorPage[UserActionSummary]:
        """Return cursor-paginated user actions with optional filtering."""
        page = await self._user_action_repository.find_with_cursor(cursor_params, filters)
        identifiers = [action.about_entity_mention for action in page.results]
        entity_mentions = await self._entity_mention_repository.find_by_identifiers(
            identifiers,
        )
        mention_map = self._index_by_identifier(entity_mentions)

        return CursorPage(
            results=[self._to_user_action_summary(action, mention_map) for action in page.results],
            count=page.count,
            next_cursor=page.next_cursor,
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

    async def get_selected_cluster_preview(
        self,
        action_id: str,
        canonical_entity_service: CanonicalEntityService,
    ) -> CanonicalEntityPreview | None:
        """Get the selected cluster preview with top entity mentions.

        Returns None when the action has no selected cluster (e.g. reject).

        Raises:
            NotFoundError: If the user action does not exist.
        """
        action = await self._get_action_or_raise(action_id)
        if action.selected_cluster is None:
            return None
        return await canonical_entity_service.build_cluster_preview(
            cluster_id=action.selected_cluster.cluster_id,
            confidence_score=action.selected_cluster.confidence_score,
            similarity_score=action.selected_cluster.similarity_score,
        )

    async def get_candidate_previews(
        self,
        action_id: str,
        pagination: PaginationParams,
        canonical_entity_service: CanonicalEntityService,
    ) -> PaginatedResult[CanonicalEntityPreview]:
        """Get paginated candidate cluster previews with top entity mentions.

        Raises:
            NotFoundError: If the user action does not exist.
        """
        action = await self._get_action_or_raise(action_id)

        selected_id = (
            action.selected_cluster.cluster_id if action.selected_cluster is not None else None
        )
        candidates = sorted(
            [c for c in action.candidates if c.cluster_id != selected_id],
            key=lambda c: c.confidence_score,
            reverse=True,
        )
        total = len(candidates)
        start = (pagination.page - 1) * pagination.per_page
        page_items = candidates[start : start + pagination.per_page]

        previews = [
            await canonical_entity_service.build_cluster_preview(
                cluster_id=c.cluster_id,
                confidence_score=c.confidence_score,
                similarity_score=c.similarity_score,
            )
            for c in page_items
        ]

        return PaginatedResult(
            count=total,
            previous=pagination.page - 1 if pagination.page > 1 else None,
            next=pagination.page + 1 if start + pagination.per_page < total else None,
            results=previews,
        )

    async def _get_action_or_raise(self, action_id: str) -> UserAction:
        action = await self._user_action_repository.find_by_id(action_id)
        if action is None:
            raise NotFoundError("UserAction", action_id)
        return action

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
