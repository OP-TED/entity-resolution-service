from httpx import AsyncClient

BASE_URL = "/api/v1/curation/entity-types"


class TestListEntityTypes:
    async def test_returns_sorted_entity_types_with_display_name_field(
        self,
        client: AsyncClient,
    ) -> None:
        response = await client.get(BASE_URL)

        assert response.status_code == 200
        data = response.json()
        assert data == [
            {"name": "ORGANISATION", "display_name_field": "legal_name"},
            {"name": "PROCEDURE", "display_name_field": "title"},
        ]

    async def test_returns_list_type(
        self,
        client: AsyncClient,
    ) -> None:
        response = await client.get(BASE_URL)

        assert response.status_code == 200
        assert isinstance(response.json(), list)
