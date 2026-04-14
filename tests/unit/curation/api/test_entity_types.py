from httpx import AsyncClient

BASE_URL = "/api/v1/curation/entity-types"


class TestListEntityTypes:
    async def test_returns_sorted_entity_types(
        self,
        client: AsyncClient,
    ) -> None:
        response = await client.get(BASE_URL)

        assert response.status_code == 200
        data = response.json()
        assert data == ["ORGANISATION", "PROCEDURE"]

    async def test_returns_list_type(
        self,
        client: AsyncClient,
    ) -> None:
        response = await client.get(BASE_URL)

        assert response.status_code == 200
        assert isinstance(response.json(), list)
