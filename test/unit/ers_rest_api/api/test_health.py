from httpx import AsyncClient


class TestHealth:
    async def test_health_returns_ok(self, client: AsyncClient) -> None:
        response = await client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["supported_entity_types"] == [
            {"name": "ORGANISATION", "rdf_type": "org:Organization"},
            {"name": "PROCEDURE", "rdf_type": "epo:Procedure"},
        ]
