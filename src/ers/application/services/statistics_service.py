import asyncio

from ers.application.dtos import Statistics, StatisticsFilters
from ers.application.ports.statistics_repository import StatisticsRepository


class StatisticsService:
    """Aggregates curation and registry statistics."""

    def __init__(
        self,
        statistics_repository: StatisticsRepository,
    ) -> None:
        self._statistics_repository = statistics_repository

    async def get_statistics(
        self,
        filters: StatisticsFilters,
    ) -> Statistics:
        """Retrieve aggregated statistics for the curation dashboard."""
        curation, registry = await asyncio.gather(
            self._statistics_repository.get_curation_statistics(filters),
            self._statistics_repository.get_registry_statistics(filters),
        )
        return Statistics(registry=registry, curation=curation)
