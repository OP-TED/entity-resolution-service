from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, create_autospec

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ers.commons.services.exceptions import ServiceUnavailableError
from ers.curation.entrypoints.api.app import create_app
from ers.curation.entrypoints.api.auth import get_current_user
from ers.curation.entrypoints.api.dependencies import (
    get_decision_curation_service,
    get_rdf_config,
)
from ers.curation.services import DecisionCurationService
from ers.rdf_mention_parser.domain.rdf_mapping_config import (
    EntityTypeConfig,
    RDFMappingConfig,
)
from ers.users.domain.data_transfer_objects import UserContext

_TEST_USER = UserContext(
    id="test-user-id",
    email="test@example.com",
    is_active=True,
    is_superuser=True,
    is_verified=True,
)

_RDF_CONFIG = RDFMappingConfig(
    namespaces={"org": "http://www.w3.org/ns/org#"},
    entity_types={
        "ORGANISATION": EntityTypeConfig(
            rdf_type="org:Organization",
            fields={"legal_name": "org:legalName"},
        ),
    },
)


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_prod_app(monkeypatch, svc: AsyncMock) -> FastAPI:
    """Build a non-debug app so the Exception handler is exercised."""
    monkeypatch.setenv("APP_NAME", "Test ERS")
    monkeypatch.setenv("DEBUG", "false")
    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    app.dependency_overrides[get_rdf_config] = lambda: _RDF_CONFIG
    app.dependency_overrides[get_decision_curation_service] = lambda: svc
    app.dependency_overrides[get_current_user] = lambda: _TEST_USER
    return app


class TestServiceUnavailableHandler:
    async def test_service_unavailable_returns_503(
        self,
        app,
        decision_curation_service,
    ) -> None:
        decision_curation_service.list_decisions.side_effect = ServiceUnavailableError(
            "MongoDB is down"
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/curation/decisions")

        assert response.status_code == 503
        body = response.json()
        assert body["error_code"] == "SERVICE_UNAVAILABLE"
        assert body["message"]


class TestUnhandledExceptionHandler:
    async def test_unhandled_exception_returns_500(self, monkeypatch) -> None:
        svc = create_autospec(DecisionCurationService, instance=True)
        svc.list_decisions.side_effect = RuntimeError("boom")

        prod_app = _make_prod_app(monkeypatch, svc)

        async with AsyncClient(
            transport=ASGITransport(app=prod_app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/curation/decisions")

        assert response.status_code == 500
        body = response.json()
        assert body["error_code"] == "SERVICE_ERROR"
        assert body["message"] == "Internal server error"
