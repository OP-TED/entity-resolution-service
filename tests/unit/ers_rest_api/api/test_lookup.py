from datetime import UTC, datetime
from unittest.mock import AsyncMock

from erspec.models.core import ClusterReference, EntityMentionIdentifier
from httpx import AsyncClient

from ers.ers_rest_api.domain.errors import ErrorCode
from ers.ers_rest_api.domain.lookup import LookupResponse
from ers.ers_rest_api.services.exceptions import MentionNotFoundError


class TestLookupEndpoint:
    async def test_known_mention_returns_200(
        self,
        client: AsyncClient,
        lookup_service: AsyncMock,
    ) -> None:
        lookup_service.handle_lookup.return_value = LookupResponse(
            identified_by=EntityMentionIdentifier(
                source_id="SYSTEM_A",
                request_id="req-001",
                entity_type="ORGANISATION",
            ),
            cluster_reference=ClusterReference(
                cluster_id="cluster-010",
                confidence_score=0.95,
                similarity_score=0.92,
            ),
            last_updated=datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC),
        )

        response = await client.get(
            "/api/v1/lookup",
            params={
                "source_id": "SYSTEM_A",
                "request_id": "req-001",
                "entity_type": "ORGANISATION",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["cluster_reference"]["cluster_id"] == "cluster-010"
        assert body["last_updated"] is not None

    async def test_unknown_mention_returns_404(
        self,
        client: AsyncClient,
        lookup_service: AsyncMock,
    ) -> None:
        lookup_service.handle_lookup.side_effect = MentionNotFoundError(
            "SYSTEM_UNKNOWN", "req-999", "ORGANISATION"
        )

        response = await client.get(
            "/api/v1/lookup",
            params={
                "source_id": "SYSTEM_UNKNOWN",
                "request_id": "req-999",
                "entity_type": "ORGANISATION",
            },
        )

        assert response.status_code == 404
        body = response.json()
        assert body["error_code"] == ErrorCode.MENTION_NOT_FOUND

    async def test_missing_source_id_returns_400(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/lookup",
            params={"request_id": "req-001", "entity_type": "ORGANISATION"},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == ErrorCode.VALIDATION_ERROR
        assert "source_id" in body["detail"]

    async def test_missing_request_id_returns_400(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/lookup",
            params={"source_id": "SYSTEM_A", "entity_type": "ORGANISATION"},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == ErrorCode.VALIDATION_ERROR
        assert "request_id" in body["detail"]

    async def test_missing_entity_type_returns_400(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/lookup",
            params={"source_id": "SYSTEM_A", "request_id": "req-001"},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == ErrorCode.VALIDATION_ERROR
        assert "entity_type" in body["detail"]

    async def test_empty_source_id_returns_400(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/lookup",
            params={"source_id": "", "request_id": "req-001", "entity_type": "ORGANISATION"},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == ErrorCode.VALIDATION_ERROR
