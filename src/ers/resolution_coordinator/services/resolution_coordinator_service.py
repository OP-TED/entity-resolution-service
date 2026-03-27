from abc import ABC, abstractmethod

from erspec.models.core import EntityMention

from ers.commons.adapters.decision_repository import DecisionRepository
from ers.ers_rest_api.domain.resolution import EntityMentionResolutionResult
from ers.request_registry.adapters.records_repository import ResolutionRequestRepository


# Temporary abstractions and DI
class ResolutionCoordinatorServiceABC(ABC):
    """Abstraction for the Resolution Coordinator (EPIC-06).

    Handles entity mention intake and returns a canonical or provisional cluster ID.
    """

    def __init__(
        self,
        resolution_request_repository: ResolutionRequestRepository,
        decision_repository: DecisionRepository,
    ) -> None:
        self._resolution_request_repository = resolution_request_repository
        self._decision_repository = decision_repository

    @abstractmethod
    async def resolve(self, entity_mention: EntityMention) -> EntityMentionResolutionResult:
        """Resolve an entity mention and return its cluster assignment."""
