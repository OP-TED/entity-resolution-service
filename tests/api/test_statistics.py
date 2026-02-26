from unittest.mock import AsyncMock

from httpx import AsyncClient

from ers.application.dtos import CurationStatistics, RegistryStatistics, Statistics


BASE_URL = "/api/v1/curation/stats"


class TestGetStatistics:
    async def test_returns_statistics(
        self,
        client: AsyncClient,
        statistics_service: AsyncMock,
    ) -> None:
        stats = Statistics(
            registry=RegistryStatistics(
                total_entity_mentions=100,
                total_canonical_entities=50,
                average_cluster_size=2.0,
                resolution_requests=10,
            ),
            curation=CurationStatistics(
                total_decisions=80,
                selected_top=40,
                selected_alternative=25,
                rejected_all=15,
            ),
        )
        statistics_service.get_statistics.return_value = stats

        response = await client.get(BASE_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["registry"]["total_entity_mentions"] == 100
        assert data["curation"]["selected_top"] == 40

    async def test_passes_filters_to_service(
        self,
        client: AsyncClient,
        statistics_service: AsyncMock,
    ) -> None:
        stats = Statistics(
            registry=RegistryStatistics(
                total_entity_mentions=0,
                total_canonical_entities=0,
                average_cluster_size=0.0,
                resolution_requests=0,
            ),
            curation=CurationStatistics(
                total_decisions=0,
                selected_top=0,
                selected_alternative=0,
                rejected_all=0,
            ),
        )
        statistics_service.get_statistics.return_value = stats

        await client.get(BASE_URL, params={"entity_type": "ORGANISATION"})

        call_args = statistics_service.get_statistics.call_args
        filters = call_args.kwargs["filters"]
        assert filters.entity_type.value == "ORGANISATION"
