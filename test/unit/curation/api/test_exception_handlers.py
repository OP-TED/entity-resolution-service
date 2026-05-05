from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
from ers.users.domain.data_transfer_objects import UserContext

_TEST_USER = UserContext(
    id="test-user-id",
    email="test@example.com",
    is_active=True,
    is_superuser=True,
    is_verified=True,
)


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


@pytest.fixture
def prod_app(monkeypatch, rdf_config, decision_curation_service) -> FastAPI:
    """Non-debug app that exercises the catch-all Exception handler.

    The standard ``app`` fixture uses ``DEBUG=true``, which causes Starlette to
    bypass the registered Exception handler and return an HTML debug page instead.
    This fixture forces ``DEBUG=false`` so the handler is exercised in tests.
    Uses the ``rdf_config`` and ``decision_curation_service`` fixtures from conftest
    so DI overrides stay consistent with the rest of the test suite.
    """
    monkeypatch.setenv("APP_NAME", "Test ERS")
    monkeypatch.setenv("DEBUG", "false")
    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    app.dependency_overrides[get_rdf_config] = lambda: rdf_config
    app.dependency_overrides[get_decision_curation_service] = lambda: decision_curation_service
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
    async def test_unhandled_exception_returns_500(
        self, prod_app, decision_curation_service
    ) -> None:
        decision_curation_service.list_decisions.side_effect = RuntimeError("boom")

        async with AsyncClient(
            transport=ASGITransport(app=prod_app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/curation/decisions")

        assert response.status_code == 500
        body = response.json()
        assert body["error_code"] == "SERVICE_ERROR"
        assert body["message"] == "Internal server error"
