from unittest.mock import AsyncMock

from httpx import AsyncClient

from ers.ers_rest_api.domain.data_transfer_objects import ResolutionOutcome, ResolveResponse

VALID_RESOLVE_PAYLOAD = {
    "source_id": "SYSTEM_A",
    "request_id": "req-001",
    "entity_type": "ORGANISATION",
    "content": '{"name": "Acme Corp"}',
    "content_type": "application/ld+json",
    "context": "notice-2024-01",
}


class TestResolveEndpoint:
    async def test_canonical_resolution_returns_200(
        self,
        client: AsyncClient,
        resolve_service: AsyncMock,
    ) -> None:
        resolve_service.handle_resolve.return_value = ResolveResponse(
            canonical_entity_id="cluster-010",
            status=ResolutionOutcome.CANONICAL,
            request_id="req-001",
        )

        response = await client.post("/api/v1/resolve", json=VALID_RESOLVE_PAYLOAD)

        assert response.status_code == 200
        body = response.json()
        assert body["canonical_entity_id"] == "cluster-010"
        assert body["status"] == "CANONICAL"
        assert body["request_id"] == "req-001"

    async def test_provisional_resolution_returns_202(
        self,
        client: AsyncClient,
        resolve_service: AsyncMock,
    ) -> None:
        resolve_service.handle_resolve.return_value = ResolveResponse(
            canonical_entity_id="prov-singleton-001",
            status=ResolutionOutcome.PROVISIONAL,
            request_id="req-010",
        )
        payload = {**VALID_RESOLVE_PAYLOAD, "request_id": "req-010"}

        response = await client.post("/api/v1/resolve", json=payload)

        assert response.status_code == 202
        body = response.json()
        assert body["canonical_entity_id"] == "prov-singleton-001"
        assert body["status"] == "PROVISIONAL"

    async def test_missing_source_id_returns_422(self, client: AsyncClient) -> None:
        payload = {k: v for k, v in VALID_RESOLVE_PAYLOAD.items() if k != "source_id"}

        response = await client.post("/api/v1/resolve", json=payload)

        assert response.status_code == 422

    async def test_missing_request_id_returns_422(self, client: AsyncClient) -> None:
        payload = {k: v for k, v in VALID_RESOLVE_PAYLOAD.items() if k != "request_id"}

        response = await client.post("/api/v1/resolve", json=payload)

        assert response.status_code == 422

    async def test_missing_entity_type_returns_422(self, client: AsyncClient) -> None:
        payload = {k: v for k, v in VALID_RESOLVE_PAYLOAD.items() if k != "entity_type"}

        response = await client.post("/api/v1/resolve", json=payload)

        assert response.status_code == 422

    async def test_missing_content_returns_422(self, client: AsyncClient) -> None:
        payload = {k: v for k, v in VALID_RESOLVE_PAYLOAD.items() if k != "content"}

        response = await client.post("/api/v1/resolve", json=payload)

        assert response.status_code == 422

    async def test_empty_source_id_returns_422(self, client: AsyncClient) -> None:
        payload = {**VALID_RESOLVE_PAYLOAD, "source_id": ""}

        response = await client.post("/api/v1/resolve", json=payload)

        assert response.status_code == 422

    async def test_malformed_json_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/resolve",
            content=b"{bad json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 422
