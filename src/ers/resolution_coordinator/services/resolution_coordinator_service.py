from abc import ABC, abstractmethod

from erspec.models.core import EntityMention

from ers.commons.adapters.decision_repository import DecisionRepository
from ers.commons.adapters.entity_mention_repository import EntityMentionRepository
from ers.ers_rest_api.domain.resolution import EntityMentionResolutionResult


# Temporary abstractions and DI
class ResolutionCoordinatorServiceABC(ABC):
    """Abstraction for the Resolution Coordinator (EPIC-06).

    Handles entity mention intake and returns a canonical or provisional cluster ID.
    """

    def __init__(
        self,
        entity_mention_repository: EntityMentionRepository,
        decision_repository: DecisionRepository,
    ) -> None:
        self._entity_mention_repository = entity_mention_repository
        self._decision_repository = decision_repository

    @abstractmethod
    async def resolve(self, entity_mention: EntityMention) -> EntityMentionResolutionResult:
        """Resolve an entity mention and return its cluster assignment."""
