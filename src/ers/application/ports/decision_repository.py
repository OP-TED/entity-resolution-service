from abc import abstractmethod

from erspec.models.core import Decision, EntityMentionIdentifier

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
        mention_identifiers: list[EntityMentionIdentifier] | None = None,
    ) -> PaginatedResult[Decision]:
        """Find decisions matching filters with pagination.

        Args:
            filters: Filter criteria for decision retrieval.
            pagination: Pagination parameters (page, per page).
            mention_identifiers: When provided, restricts results to decisions
                whose ``about_entity_mention`` is in this list (used for
                full-text search pre-filtering).
        """

    @abstractmethod
    async def find_mention_ids_by_cluster(
        self,
        cluster_id: str,
        limit: int,
    ) -> list[EntityMentionIdentifier]:
        """Return entity mention identifiers for decisions placed in a cluster."""

    @abstractmethod
    async def count_distinct_clusters(self) -> int:
        """Return the number of distinct cluster IDs across all decisions."""

    @abstractmethod
    async def average_cluster_size(self) -> float:
        """Return the average number of decisions per cluster."""
