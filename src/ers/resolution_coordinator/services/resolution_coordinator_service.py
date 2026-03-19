from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from erspec.models.core import EntityMention

# Temporary abstractions


class ResolutionOutcome(StrEnum):
    CANONICAL = "CANONICAL"
    PROVISIONAL = "PROVISIONAL"


@dataclass(frozen=True)
class ResolutionResult:
    """Result returned by the Resolution Coordinator after handling an entity mention intake."""

    canonical_entity_id: str
    outcome: ResolutionOutcome
    request_id: str


class ResolutionCoordinatorServiceABC(ABC):
    """Abstraction for the Resolution Coordinator (EPIC-06).

    Handles entity mention intake and returns a canonical or provisional cluster ID.
    """

    @abstractmethod
    async def resolve(self, entity_mention: EntityMention) -> ResolutionResult:
        """Resolve an entity mention and return its cluster assignment."""
