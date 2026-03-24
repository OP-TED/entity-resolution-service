from abc import ABC, abstractmethod
from datetime import datetime

from erspec.models.core import Decision, LookupState

from ers.commons.adapters.decision_repository import DecisionRepository
from ers.resolution_decision_store.domain.data_transfer_objects import DeltaPage


# Temporary abstractions and DI
class ResolutionDecisionStoreServiceABC(ABC):
    """Abstraction for the Resolution Decision Store (EPIC-04).

    Provides read access to decisions and manages delta-sync snapshots.
    """

    def __init__(self, decision_repository: DecisionRepository) -> None:
        self._decision_repository = decision_repository

    @abstractmethod
    async def get_decision_for_mention(
        self,
        source_id: str,
        request_id: str,
        entity_type: str,
    ) -> Decision | None:
        """Retrieve the current decision for a mention triad."""

    @abstractmethod
    async def get_delta_for_source(
        self,
        source_id: str,
        last_snapshot: datetime | None,
        limit: int,
        continuation_cursor: str | None,
    ) -> DeltaPage:
        """Retrieve a page of changed assignments since the last snapshot."""

    @abstractmethod
    async def get_lookup_state(self, source_id: str) -> LookupState | None:
        """Retrieve the synchronisation snapshot for a source."""

    @abstractmethod
    async def advance_snapshot(self, source_id: str, snapshot: datetime) -> None:
        """Advance the synchronisation snapshot for a source."""
