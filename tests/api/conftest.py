from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, create_autospec

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ers.application.services import (
    CanonicalEntityService,
    DecisionCurationService,
    EntityService,
    StatisticsService,
)
from ers.config import Settings
from ers.entrypoints.api.app import create_app
from ers.entrypoints.api.dependencies import (
    get_canonical_entity_service,
    get_decision_curation_service,
    get_entity_service,
    get_statistics_service,
)


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


@pytest.fixture
def settings() -> Settings:
    return Settings(app_name="Test ERS", debug=True)


@pytest.fixture
def decision_curation_service() -> AsyncMock:
    return create_autospec(DecisionCurationService, instance=True)


@pytest.fixture
def canonical_entity_service() -> AsyncMock:
    return create_autospec(CanonicalEntityService, instance=True)


@pytest.fixture
def entity_service() -> AsyncMock:
    return create_autospec(EntityService, instance=True)


@pytest.fixture
def statistics_service() -> AsyncMock:
    return create_autospec(StatisticsService, instance=True)


@pytest.fixture
def app(
    settings: Settings,
    decision_curation_service: AsyncMock,
    canonical_entity_service: AsyncMock,
    entity_service: AsyncMock,
    statistics_service: AsyncMock,
) -> FastAPI:
    app = create_app(settings=settings)
    app.router.lifespan_context = _noop_lifespan
    app.dependency_overrides[get_decision_curation_service] = lambda: (
        decision_curation_service
    )
    app.dependency_overrides[get_canonical_entity_service] = lambda: (
        canonical_entity_service
    )
    app.dependency_overrides[get_entity_service] = lambda: entity_service
    app.dependency_overrides[get_statistics_service] = lambda: statistics_service
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, Any]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
