from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, create_autospec

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ers.ers_rest_api.entrypoints.api.app import create_app
from ers.ers_rest_api.entrypoints.api.dependencies import (
    get_lookup_service,
    get_refresh_bulk_service,
    get_resolve_service,
)
from ers.ers_rest_api.services.lookup_service import LookupService
from ers.ers_rest_api.services.refresh_bulk_service import RefreshBulkService
from ers.ers_rest_api.services.resolve_service import ResolveService


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


@pytest.fixture
def resolve_service() -> AsyncMock:
    return create_autospec(ResolveService, instance=True)


@pytest.fixture
def lookup_service() -> AsyncMock:
    return create_autospec(LookupService, instance=True)


@pytest.fixture
def refresh_bulk_service() -> AsyncMock:
    return create_autospec(RefreshBulkService, instance=True)


@pytest.fixture
def app(
    monkeypatch,
    resolve_service: AsyncMock,
    lookup_service: AsyncMock,
    refresh_bulk_service: AsyncMock,
) -> FastAPI:
    monkeypatch.setenv("ERS_API_NAME", "Test ERS API")
    monkeypatch.setenv("DEBUG", "false")
    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    app.dependency_overrides[get_resolve_service] = lambda: resolve_service
    app.dependency_overrides[get_lookup_service] = lambda: lookup_service
    app.dependency_overrides[get_refresh_bulk_service] = lambda: refresh_bulk_service
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, Any]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
