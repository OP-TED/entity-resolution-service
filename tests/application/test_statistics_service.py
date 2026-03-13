from unittest.mock import MagicMock, create_autospec

import pytest
from erspec.models.core import EntityType

from ers.application.dtos import (
    CurationStatistics,
    RegistryStatistics,
    Statistics,
    StatisticsFilters,
)
from ers.application.ports.statistics_repository import StatisticsRepository
from ers.application.services.statistics_service import StatisticsService


@pytest.fixture
def statistics_repository() -> MagicMock:
    return create_autospec(StatisticsRepository, instance=True)


@pytest.fixture
def service(statistics_repository: MagicMock) -> StatisticsService:
    return StatisticsService(statistics_repository=statistics_repository)


class TestGetStatistics:
    async def test_returns_aggregated_statistics(
        self,
        service: StatisticsService,
        statistics_repository: MagicMock,
    ) -> None:
        curation = CurationStatistics(
            total_decisions=100,
            selected_top=50,
            selected_alternative=30,
            rejected_all=20,
        )
        registry = RegistryStatistics(
            total_entity_mentions=5000,
            total_canonical_entities=1000,
            average_cluster_size=5.0,
            resolution_requests=3000,
        )
        statistics_repository.get_curation_statistics.return_value = curation
        statistics_repository.get_registry_statistics.return_value = registry

        result = await service.get_statistics(filters=StatisticsFilters())

        assert isinstance(result, Statistics)
        assert result.curation == curation
        assert result.registry == registry

    async def test_passes_filters_to_repository(
        self,
        service: StatisticsService,
        statistics_repository: MagicMock,
    ) -> None:
        filters = StatisticsFilters(entity_type=EntityType.ORGANISATION)
        statistics_repository.get_curation_statistics.return_value = CurationStatistics(
            total_decisions=0,
            selected_top=0,
            selected_alternative=0,
            rejected_all=0,
        )
        statistics_repository.get_registry_statistics.return_value = RegistryStatistics(
            total_entity_mentions=0,
            total_canonical_entities=0,
            average_cluster_size=0.0,
            resolution_requests=0,
        )

        await service.get_statistics(filters=filters)

        statistics_repository.get_curation_statistics.assert_called_once_with(filters)
        statistics_repository.get_registry_statistics.assert_called_once_with(filters)
