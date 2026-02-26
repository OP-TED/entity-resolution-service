from abc import abstractmethod

from erspec.models.core import EntityMention, EntityMentionIdentifier

from ers.application.ports.repositories import AsyncReadRepository


class EntityMentionRepository(
    AsyncReadRepository[EntityMention, EntityMentionIdentifier],
):
    """Read-only repository for entity mention retrieval."""

    @abstractmethod
    async def find_by_identifiers(
        self,
        identifiers: list[EntityMentionIdentifier],
        limit: int | None = None,
    ) -> list[EntityMention]:
        """Batch-fetch entity mentions by their identifiers."""
