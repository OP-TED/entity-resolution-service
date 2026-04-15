from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, create_autospec

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ers.curation.entrypoints.api.app import create_app
from ers.curation.entrypoints.api.auth import get_current_user
from ers.curation.entrypoints.api.dependencies import (
    get_auth_service,
    get_canonical_entity_service,
    get_decision_curation_service,
    get_entity_service,
    get_rdf_config,
    get_statistics_service,
    get_user_action_service,
    get_user_management_service,
)
from ers.curation.services import (
    CanonicalEntityService,
    DecisionCurationService,
    EntityService,
    StatisticsService,
    UserActionService,
)
from ers.rdf_mention_parser.domain.rdf_mapping_config import (
    EntityTypeConfig,
    RDFMappingConfig,
)
from ers.users.domain.data_transfer_objects import UserContext
from ers.users.services import AuthService, UserManagementService

TEST_USER_CONTEXT = UserContext(
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
def rdf_config() -> RDFMappingConfig:
    return RDFMappingConfig(
        namespaces={
            "org": "http://www.w3.org/ns/org#",
            "epo": "http://data.europa.eu/a4g/ontology#",
        },
        entity_types={
            "ORGANISATION": EntityTypeConfig(
                rdf_type="org:Organization",
                fields={"legal_name": "epo:hasLegalName"},
            ),
            "PROCEDURE": EntityTypeConfig(
                rdf_type="epo:Procedure",
                fields={"title": "epo:hasTitle"},
            ),
        },
    )


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
def auth_service() -> AsyncMock:
    return create_autospec(AuthService, instance=True)


@pytest.fixture
def user_management_service() -> AsyncMock:
    return create_autospec(UserManagementService, instance=True)


@pytest.fixture
def user_action_service() -> AsyncMock:
    return create_autospec(UserActionService, instance=True)


@pytest.fixture
def app(
    monkeypatch,
    rdf_config: RDFMappingConfig,
    decision_curation_service: AsyncMock,
    canonical_entity_service: AsyncMock,
    entity_service: AsyncMock,
    statistics_service: AsyncMock,
    auth_service: AsyncMock,
    user_action_service: AsyncMock,
    user_management_service: AsyncMock,
) -> FastAPI:
    # monkeypatch.setenv calls MUST come before create_app() — properties are
    # evaluated at access time, so env vars must be set before FastAPI reads them.
    monkeypatch.setenv("APP_NAME", "Test ERS")
    monkeypatch.setenv("DEBUG", "true")
    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    app.dependency_overrides[get_rdf_config] = lambda: rdf_config
    app.dependency_overrides[get_decision_curation_service] = lambda: decision_curation_service
    app.dependency_overrides[get_canonical_entity_service] = lambda: canonical_entity_service
    app.dependency_overrides[get_entity_service] = lambda: entity_service
    app.dependency_overrides[get_statistics_service] = lambda: statistics_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_user_action_service] = lambda: user_action_service
    app.dependency_overrides[get_user_management_service] = lambda: user_management_service
    app.dependency_overrides[get_current_user] = lambda: TEST_USER_CONTEXT
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, Any]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
