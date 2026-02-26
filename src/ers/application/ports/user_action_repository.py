from abc import abstractmethod
from datetime import datetime

from erspec.models.core import EntityMentionIdentifier, UserAction

from ers.application.ports.repositories import AsyncWriteRepository


class UserActionRepository(AsyncWriteRepository[UserAction, str]):
    """Repository for persisting user action (curation) entries."""

    @abstractmethod
    async def has_current_action(
        self,
        about_entity_mention: EntityMentionIdentifier,
        since: datetime,
    ) -> bool:
        """Check if a UserAction exists for this entity mention since the given timestamp."""
