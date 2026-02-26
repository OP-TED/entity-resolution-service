from abc import abstractmethod

from erspec.models.core import Decision

from ers.application.dtos import DecisionFilters, PaginatedResult, PaginationParams
from ers.application.ports.repositories import AsyncReadRepository, AsyncWriteRepository


class DecisionRepository(
    AsyncReadRepository[Decision, str],
    AsyncWriteRepository[Decision, str],
):
    """Repository for decision projection persistence and querying."""

    @abstractmethod
    async def find_with_filters(
        self,
        filters: DecisionFilters,
        pagination: PaginationParams,
    ) -> PaginatedResult[Decision]:
        """Find decisions matching filters with pagination."""
