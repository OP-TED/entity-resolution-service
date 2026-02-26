from datetime import datetime, timezone
from uuid import uuid4

from erspec.models.core import (
    ClusterReference,
    Decision,
    UserAction,
    UserActionType,
)

from ers.domain.exceptions import InvalidClusterError


class UserActionFactory:
    """Factory for creating UserAction instances from curation commands."""

    @staticmethod
    def _find_candidate(decision: Decision, cluster_id: str) -> ClusterReference:
        for candidate in decision.candidates:
            if candidate.cluster_id == cluster_id:
                return candidate
        raise InvalidClusterError(cluster_id, decision.id)

    @staticmethod
    def create_accept(actor: str, decision: Decision) -> UserAction:
        """Create a UserAction for accepting the top candidate."""
        return UserAction(
            id=str(uuid4()),
            about_entity_mention=decision.about_entity_mention,
            candidates=decision.candidates,
            selected_cluster=decision.current_placement,
            action_type=UserActionType.ACCEPT_TOP,
            actor=actor,
            created_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def create_reject(actor: str, decision: Decision) -> UserAction:
        """Create a UserAction for rejecting all candidates."""
        return UserAction(
            id=str(uuid4()),
            about_entity_mention=decision.about_entity_mention,
            candidates=decision.candidates,
            selected_cluster=None,
            action_type=UserActionType.REJECT_ALL,
            actor=actor,
            created_at=datetime.now(timezone.utc),
        )

    @classmethod
    def create_assign(
        cls, actor: str, decision: Decision, cluster_id: str
    ) -> UserAction:
        """Create a UserAction for selecting an alternative candidate.

        Raises:
            InvalidClusterError: If cluster_id is not in candidates.
        """
        target = cls._find_candidate(decision, cluster_id)
        return UserAction(
            id=str(uuid4()),
            about_entity_mention=decision.about_entity_mention,
            candidates=decision.candidates,
            selected_cluster=target,
            action_type=UserActionType.ACCEPT_ALTERNATIVE,
            actor=actor,
            created_at=datetime.now(timezone.utc),
        )
