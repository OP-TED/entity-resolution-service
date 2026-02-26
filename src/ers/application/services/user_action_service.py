from erspec.models.core import Decision

from ers.application.ports.user_action_repository import UserActionRepository
from ers.domain.exceptions import AlreadyCuratedError
from ers.domain.models import UserActionFactory


class UserActionService:
    """Creates and persists user action entries for curation commands."""

    def __init__(self, user_action_repository: UserActionRepository) -> None:
        self._user_action_repository = user_action_repository

    async def _check_not_already_curated(self, decision: Decision) -> None:
        """Raise AlreadyCuratedError if decision was already curated on its current version."""
        if decision.updated_at is not None:
            already_curated = await self._user_action_repository.has_current_action(
                about_entity_mention=decision.about_entity_mention,
                since=decision.updated_at,
            )
            if already_curated:
                raise AlreadyCuratedError(decision.id)

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

    async def record_assign(
        self, actor: str, decision: Decision, cluster_id: str
    ) -> None:
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
