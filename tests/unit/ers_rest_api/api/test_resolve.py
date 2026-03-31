from unittest.mock import AsyncMock

from erspec.models.core import EntityMentionIdentifier
from httpx import AsyncClient

from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.ers_rest_api.domain.errors import ErrorCode
from ers.ers_rest_api.domain.resolution import (
    BulkResolveResponse,
    EntityMentionResolutionResult,
)

VALID_RESOLVE_PAYLOAD = {
    "mention": {
        "identifiedBy": {
            "source_id": "SYSTEM_A",
            "request_id": "req-001",
            "entity_type": "ORGANISATION",
        },
        "content": '{"name": "Acme Corp"}',
        "content_type": "application/ld+json",
    },
}


class TestResolveEndpoint:
    async def test_canonical_resolution_returns_200(
        self,
        client: AsyncClient,
        resolve_service: AsyncMock,
    ) -> None:
        resolve_service.handle_resolve.return_value = EntityMentionResolutionResult(
            identified_by=EntityMentionIdentifier(
                source_id="SYSTEM_A",
                request_id="req-001",
                entity_type="ORGANISATION",
            ),
            canonical_entity_id="cluster-010",
            status=ResolutionOutcome.CANONICAL,
        )

        response = await client.post("/api/v1/resolve", json=VALID_RESOLVE_PAYLOAD)

        assert response.status_code == 200
        body = response.json()
        assert body["canonical_entity_id"] == "cluster-010"
        assert body["status"] == "CANONICAL"
        assert body["identified_by"]["request_id"] == "req-001"

    async def test_provisional_resolution_returns_202(
        self,
        client: AsyncClient,
        resolve_service: AsyncMock,
    ) -> None:
        resolve_service.handle_resolve.return_value = EntityMentionResolutionResult(
            identified_by=EntityMentionIdentifier(
                source_id="SYSTEM_A",
                request_id="req-010",
                entity_type="ORGANISATION",
            ),
            canonical_entity_id="prov-singleton-001",
            status=ResolutionOutcome.PROVISIONAL,
        )

        payload = {
            "mention": {
                "identifiedBy": {
                    "source_id": "SYSTEM_A",
                    "request_id": "req-010",
                    "entity_type": "ORGANISATION",
                },
                "content": '{"name": "Acme Corp"}',
                "content_type": "application/ld+json",
            },
        }

        response = await client.post("/api/v1/resolve", json=payload)

        assert response.status_code == 202
        body = response.json()
        assert body["canonical_entity_id"] == "prov-singleton-001"
        assert body["status"] == "PROVISIONAL"

    async def test_missing_source_id_returns_400(self, client: AsyncClient) -> None:
        payload = {
            "mention": {
                "identifiedBy": {
                    "request_id": "req-001",
                    "entity_type": "ORGANISATION",
                },
                "content": '{"name": "Acme Corp"}',
            },
        }

        response = await client.post("/api/v1/resolve", json=payload)

        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == ErrorCode.VALIDATION_ERROR
        assert "source_id" in body["detail"]

    async def test_missing_request_id_returns_400(self, client: AsyncClient) -> None:
        payload = {
            "mention": {
                "identifiedBy": {
                    "source_id": "SYSTEM_A",
                    "entity_type": "ORGANISATION",
                },
                "content": '{"name": "Acme Corp"}',
            },
        }

        response = await client.post("/api/v1/resolve", json=payload)

        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == ErrorCode.VALIDATION_ERROR
        assert "request_id" in body["detail"]

    async def test_missing_entity_type_returns_400(self, client: AsyncClient) -> None:
        payload = {
            "mention": {
                "identifiedBy": {
                    "source_id": "SYSTEM_A",
                    "request_id": "req-001",
                },
                "content": '{"name": "Acme Corp"}',
            },
        }

        response = await client.post("/api/v1/resolve", json=payload)

        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == ErrorCode.VALIDATION_ERROR
        assert "entity_type" in body["detail"]

    async def test_missing_content_returns_400(self, client: AsyncClient) -> None:
        payload = {
            "mention": {
                "identifiedBy": {
                    "source_id": "SYSTEM_A",
                    "request_id": "req-001",
                    "entity_type": "ORGANISATION",
                },
                "content_type": "application/ld+json",
            },
        }

        response = await client.post("/api/v1/resolve", json=payload)

        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == ErrorCode.VALIDATION_ERROR
        assert "content" in body["detail"]

    async def test_malformed_json_returns_400(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/resolve",
            content=b"{bad json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == ErrorCode.VALIDATION_ERROR


class TestResolveBulkEndpoint:
    async def test_returns_200_with_results(
        self,
        client: AsyncClient,
        resolve_service: AsyncMock,
    ) -> None:
        resolve_service.handle_bulk_resolve.return_value = BulkResolveResponse(
            results=[
                EntityMentionResolutionResult(
                    identified_by=EntityMentionIdentifier(
                        source_id="SYS_A",
                        request_id="req-001",
                        entity_type="ORGANISATION",
                    ),
                    canonical_entity_id="cluster-010",
                    status=ResolutionOutcome.CANONICAL,
                ),
            ],
        )

        payload = {
            "mentions": [
                {
                    "mention": {
                        "identifiedBy": {
                            "source_id": "SYS_A",
                            "request_id": "req-001",
                            "entity_type": "ORGANISATION",
                        },
                        "content": '{"name": "Acme Corp"}',
                        "content_type": "application/ld+json",
                    },
                },
            ],
        }

        response = await client.post("/api/v1/resolve-bulk", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert len(body["results"]) == 1
        assert body["results"][0]["canonical_entity_id"] == "cluster-010"

    async def test_empty_mentions_returns_400(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/resolve-bulk", json={"mentions": []})

        assert response.status_code == 400
