from datetime import UTC, datetime
from unittest.mock import AsyncMock

from erspec.models.core import ClusterReference, EntityMentionIdentifier
from httpx import AsyncClient

from ers.ers_rest_api.domain.errors import ErrorCode
from ers.ers_rest_api.domain.lookup import (
    LookupResponse,
    RefreshBulkResponse,
)

VALID_REFRESH_BULK_PAYLOAD = {
    "source_id": "SYSTEM_C",
    "limit": 1000,
}


class TestRefreshBulkEndpoint:
    async def test_changed_assignments_returns_200(
        self,
        client: AsyncClient,
        refresh_bulk_service: AsyncMock,
    ) -> None:
        refresh_bulk_service.handle_refresh_bulk.return_value = RefreshBulkResponse(
            deltas=[
                LookupResponse(
                    identified_by=EntityMentionIdentifier(
                        source_id="SYSTEM_C",
                        request_id="req-001",
                        entity_type="ORGANISATION",
                    ),
                    cluster_reference=ClusterReference(
                        cluster_id="cluster-010",
                        confidence_score=0.9,
                        similarity_score=0.85,
                    ),
                    last_updated=datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC),
                ),
                LookupResponse(
                    identified_by=EntityMentionIdentifier(
                        source_id="SYSTEM_C",
                        request_id="req-002",
                        entity_type="ORGANISATION",
                    ),
                    cluster_reference=ClusterReference(
                        cluster_id="cluster-011",
                        confidence_score=0.9,
                        similarity_score=0.85,
                    ),
                    last_updated=datetime(2026, 3, 15, 11, 30, 0, tzinfo=UTC),
                ),
            ],
            has_more=False,
            continuation_cursor=None,
        )

        response = await client.post("/api/v1/refresh-bulk", json=VALID_REFRESH_BULK_PAYLOAD)

        assert response.status_code == 200
        body = response.json()
        assert len(body["deltas"]) == 2
        assert body["has_more"] is False
        assert body["continuation_cursor"] is None

    async def test_empty_delta_returns_200(
        self,
        client: AsyncClient,
        refresh_bulk_service: AsyncMock,
    ) -> None:
        refresh_bulk_service.handle_refresh_bulk.return_value = RefreshBulkResponse(
            deltas=[],
            has_more=False,
            continuation_cursor=None,
        )

        response = await client.post("/api/v1/refresh-bulk", json=VALID_REFRESH_BULK_PAYLOAD)

        assert response.status_code == 200
        body = response.json()
        assert len(body["deltas"]) == 0
        assert body["has_more"] is False

    async def test_paginated_response_returns_cursor(
        self,
        client: AsyncClient,
        refresh_bulk_service: AsyncMock,
    ) -> None:
        refresh_bulk_service.handle_refresh_bulk.return_value = RefreshBulkResponse(
            deltas=[
                LookupResponse(
                    identified_by=EntityMentionIdentifier(
                        source_id="SYSTEM_D",
                        request_id=f"req-{i:03d}",
                        entity_type="ORGANISATION",
                    ),
                    cluster_reference=ClusterReference(
                        cluster_id=f"cluster-{i:03d}",
                        confidence_score=0.9,
                        similarity_score=0.85,
                    ),
                    last_updated=datetime(2026, 3, 15, 10, i, 0, tzinfo=UTC),
                )
                for i in range(50)
            ],
            has_more=True,
            continuation_cursor="opaque-cursor-abc",
        )

        response = await client.post(
            "/api/v1/refresh-bulk",
            json={"source_id": "SYSTEM_D", "limit": 50},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["deltas"]) == 50
        assert body["has_more"] is True
        assert body["continuation_cursor"] == "opaque-cursor-abc"

    async def test_with_continuation_cursor(
        self,
        client: AsyncClient,
        refresh_bulk_service: AsyncMock,
    ) -> None:
        refresh_bulk_service.handle_refresh_bulk.return_value = RefreshBulkResponse(
            deltas=[],
            has_more=False,
            continuation_cursor=None,
        )

        response = await client.post(
            "/api/v1/refresh-bulk",
            json={
                "source_id": "SYSTEM_E",
                "limit": 100,
                "continuation_cursor": "opaque-cursor-xyz",
            },
        )

        assert response.status_code == 200
        refresh_bulk_service.handle_refresh_bulk.assert_called_once()

    async def test_missing_source_id_returns_400(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/refresh-bulk", json={"limit": 100})

        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == ErrorCode.VALIDATION_ERROR
        assert "source_id" in body["detail"]

    async def test_empty_source_id_returns_400(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/refresh-bulk",
            json={"source_id": "", "limit": 100},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == ErrorCode.VALIDATION_ERROR

    async def test_zero_limit_returns_400(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/refresh-bulk",
            json={"source_id": "SYSTEM_C", "limit": 0},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == ErrorCode.VALIDATION_ERROR

    async def test_negative_limit_returns_400(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/refresh-bulk",
            json={"source_id": "SYSTEM_C", "limit": -1},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == ErrorCode.VALIDATION_ERROR

    async def test_default_limit_applied(
        self,
        client: AsyncClient,
        refresh_bulk_service: AsyncMock,
    ) -> None:
        refresh_bulk_service.handle_refresh_bulk.return_value = RefreshBulkResponse(
            deltas=[],
            has_more=False,
        )

        response = await client.post(
            "/api/v1/refresh-bulk",
            json={"source_id": "SYSTEM_F"},
        )

        assert response.status_code == 200
        call_args = refresh_bulk_service.handle_refresh_bulk.call_args
        assert call_args[0][0].limit == 1000
