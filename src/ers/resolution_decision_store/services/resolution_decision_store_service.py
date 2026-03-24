from abc import ABC, abstractmethod
from datetime import datetime

from erspec.models.core import Decision, LookupState

from ers.commons.adapters.decision_repository import BaseDecisionRepository
from ers.ers_rest_api.domain.data_transfer_objects import DeltaPage


# Temporary abstractions and DI
class ResolutionDecisionStoreServiceABC(ABC):
    """Abstraction for the Resolution Decision Store (EPIC-04).

    Provides read access to decisions and manages delta-sync snapshots.
    """

    def __init__(self, decision_repository: BaseDecisionRepository) -> None:
        self._decision_repository = decision_repository

    @abstractmethod
    async def get_decision_for_mention(
        self,
        source_id: str,
        request_id: str,
        entity_type: str,
    ) -> Decision | None:
        """Retrieve the current decision for a mention triad."""
        # FIXME: already implemented by get_decision_by_triad in 
        # src/ers/resolution_decision_store/services/decision_store_service.py
        # Needs to be removed from here and references needs to be updated to use that function instead.


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
        # FIXME: already implemented in src/ers/request_registry/services/request_registry_service.py,
        # Needs to be removed from here and the references need to be updated to use that service instead.

    @abstractmethod
    async def advance_snapshot(self, source_id: str, snapshot: datetime) -> None:
        """Advance the synchronisation snapshot for a source."""
        # FIXME: already implemented in src/ers/request_registry/services/request_registry_service.py,
        # Needs to be removed from here and the references need to be updated to use that service instead.