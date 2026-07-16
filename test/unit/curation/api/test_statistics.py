from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from ers.curation.domain.data_transfer_objects import (
    CurationStatistics,
    RegistryStatistics,
    Statistics,
)

pytestmark = pytest.mark.asyncio

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
                cluster_size_average=2.0,
                cluster_size_median=2.0,
                cluster_size_p95=4,
                cluster_size_max=10,
                cluster_singletons_count=5,
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
                cluster_size_average=0.0,
                cluster_size_median=0.0,
                cluster_size_p95=0,
                cluster_size_max=0,
                cluster_singletons_count=0,
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
        assert filters.entity_type == "ORGANISATION"

    async def test_rejects_invalid_entity_type(
        self,
        client: AsyncClient,
    ) -> None:
        response = await client.get(BASE_URL, params={"entity_type": "INVALID_TYPE"})

        assert response.status_code == 400
        assert "INVALID_TYPE" in response.json()["message"]
