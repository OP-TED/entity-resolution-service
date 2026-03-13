from abc import abstractmethod
from datetime import datetime

from erspec.models.core import EntityMentionIdentifier, UserAction

from ers.commons.application.ports.repositories import AsyncWriteRepository
from ers.curation.application.dtos import PaginatedResult, PaginationParams


class UserActionRepository(AsyncWriteRepository[UserAction, str]):
    """Repository for persisting user action (curation) entries."""

    @abstractmethod
    async def find_paginated(
        self,
        pagination: PaginationParams,
    ) -> PaginatedResult[UserAction]:
        """Return paginated user actions ordered by latest first."""

    @abstractmethod
    async def has_current_action(
        self,
        about_entity_mention: EntityMentionIdentifier,
        since: datetime,
    ) -> bool:
        """Check if a UserAction exists for this entity mention since the given timestamp."""
