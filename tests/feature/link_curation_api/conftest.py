"""Shared fixtures for link_curation_api BDD feature tests.

Mocks at the **repository** boundary so that real service logic is exercised
end-to-end: HTTP request → endpoint → service → (mocked) repository → response.

Uses starlette TestClient (sync) because pytest-bdd @scenario creates sync test
functions — async steps/fixtures would return unawaited coroutines.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from fastapi import FastAPI
from pytest_bdd import given
from starlette.testclient import TestClient

from ers.curation.adapters import (
    DecisionCurationRepository,
    EntityMentionCurationRepository,
    StatisticsRepository,
    UserActionCurationRepository,
)
from ers.curation.entrypoints.api.app import create_app
from ers.curation.entrypoints.api.auth import get_current_user
from ers.curation.entrypoints.api.dependencies import (
    get_auth_service,
    get_canonical_entity_service,
    get_decision_curation_service,
    get_entity_service,
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
from ers.users.adapters.hasher import PasswordHasher
from ers.users.adapters.user_repository import UserRepository
from ers.users.domain.data_transfer_objects import UserContext
from ers.users.services import AuthService, UserManagementService
from ers.users.services.token_service import TokenService

ADMIN_USER = UserContext(
    id="admin-user-id",
    email="admin@example.com",
    is_active=True,
    is_superuser=True,
    is_verified=True,
)

VERIFIED_USER = UserContext(
    id="verified-user-id",
    email="curator@example.com",
    is_active=True,
    is_superuser=False,
    is_verified=True,
)

UNVERIFIED_USER = UserContext(
    id="unverified-user-id",
    email="unverified@example.com",
    is_active=True,
    is_superuser=False,
    is_verified=False,
)


# ---------------------------------------------------------------------------
# Mutable context
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx() -> dict[str, Any]:
    """Shared mutable context for passing state between step functions."""
    return {}


# ---------------------------------------------------------------------------
# Repository mocks (the ONLY mock boundary)
# ---------------------------------------------------------------------------


@pytest.fixture
def decision_repository() -> AsyncMock:
    return create_autospec(DecisionCurationRepository, instance=True)


@pytest.fixture
def entity_mention_repository() -> AsyncMock:
    return create_autospec(EntityMentionCurationRepository, instance=True)


@pytest.fixture
def user_action_repository() -> AsyncMock:
    return create_autospec(UserActionCurationRepository, instance=True)


@pytest.fixture
def statistics_repository() -> AsyncMock:
    return create_autospec(StatisticsRepository, instance=True)


@pytest.fixture
def user_repository() -> AsyncMock:
    return create_autospec(UserRepository, instance=True)


@pytest.fixture
def password_hasher() -> MagicMock:
    mock = create_autospec(PasswordHasher, instance=True)
    mock.hash.side_effect = lambda pw: f"hashed:{pw}"
    mock.verify.side_effect = lambda pw, hashed: hashed == f"hashed:{pw}"
    return mock


@pytest.fixture
def token_service() -> MagicMock:
    return create_autospec(TokenService, instance=True)


# ---------------------------------------------------------------------------
# Real services wired with mocked repositories
# ---------------------------------------------------------------------------


@pytest.fixture
def user_action_service(
    user_action_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> UserActionService:
    return UserActionService(
        user_action_repository=user_action_repository,
        entity_mention_repository=entity_mention_repository,
    )


@pytest.fixture
def decision_curation_service(
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
    user_action_service: UserActionService,
) -> DecisionCurationService:
    return DecisionCurationService(
        decision_repository=decision_repository,
        entity_mention_repository=entity_mention_repository,
        user_action_service=user_action_service,
    )


@pytest.fixture
def canonical_entity_service(
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> CanonicalEntityService:
    return CanonicalEntityService(
        decision_repository=decision_repository,
        entity_mention_repository=entity_mention_repository,
    )


@pytest.fixture
def entity_service(
    entity_mention_repository: AsyncMock,
) -> EntityService:
    return EntityService(entity_mention_repository=entity_mention_repository)


@pytest.fixture
def statistics_service(
    statistics_repository: AsyncMock,
) -> StatisticsService:
    return StatisticsService(statistics_repository=statistics_repository)


@pytest.fixture
def auth_service(
    user_repository: AsyncMock,
    password_hasher: MagicMock,
    token_service: MagicMock,
) -> AuthService:
    return AuthService(
        user_repository=user_repository,
        password_hasher=password_hasher,
        token_service=token_service,
    )


@pytest.fixture
def user_management_service(
    user_repository: AsyncMock,
    password_hasher: MagicMock,
) -> UserManagementService:
    return UserManagementService(
        user_repository=user_repository,
        password_hasher=password_hasher,
    )


# ---------------------------------------------------------------------------
# FastAPI app and client
# ---------------------------------------------------------------------------


@pytest.fixture
def app(
    decision_curation_service: DecisionCurationService,
    canonical_entity_service: CanonicalEntityService,
    entity_service: EntityService,
    statistics_service: StatisticsService,
    auth_service: AuthService,
    user_action_service: UserActionService,
    user_management_service: UserManagementService,
) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_decision_curation_service] = lambda: (
        decision_curation_service
    )
    application.dependency_overrides[get_canonical_entity_service] = lambda: (
        canonical_entity_service
    )
    application.dependency_overrides[get_entity_service] = lambda: entity_service
    application.dependency_overrides[get_statistics_service] = lambda: statistics_service
    application.dependency_overrides[get_auth_service] = lambda: auth_service
    application.dependency_overrides[get_user_action_service] = lambda: user_action_service
    application.dependency_overrides[get_user_management_service] = lambda: user_management_service
    application.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as tc:
        yield tc


def make_client_with_user(app: FastAPI, user: UserContext) -> TestClient:
    """Create a test client authenticated as a specific user."""
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def make_unauthenticated_client(app: FastAPI) -> TestClient:
    """Create a test client with no authentication."""
    app.dependency_overrides.pop(get_current_user, None)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Shared Background steps
# ---------------------------------------------------------------------------


@given("the curator is authenticated and verified", target_fixture="_auth_done")
def curator_authenticated() -> bool:
    return True
