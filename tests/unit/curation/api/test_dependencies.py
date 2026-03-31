from unittest.mock import MagicMock

from ers.commons.adapters.hasher import Argon2PasswordHasher
from ers.curation.adapters import (
    MongoDecisionCurationRepository,
    MongoEntityMentionCurationRepository,
    MongoStatisticsRepository,
    MongoUserActionCurationRepository,
)
from ers.curation.entrypoints.api.dependencies import (
    _get_database,
    get_auth_service,
    get_canonical_entity_service,
    get_decision_curation_service,
    get_decision_repository,
    get_entity_mention_repository,
    get_entity_service,
    get_password_hasher,
    get_statistics_repository,
    get_statistics_service,
    get_token_service,
    get_user_action_repository,
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
from ers.users.adapters import MongoUserRepository
from ers.users.services import AuthService, UserManagementService
from ers.users.services.token_service import JWTTokenService


class TestGetDatabase:
    def test_returns_mongo_db_from_app_state(self):
        mock_request = MagicMock()
        mock_request.app.state.mongo_db = "test-db"
        assert _get_database(mock_request) == "test-db"


class TestInfrastructureProviders:
    def test_get_password_hasher(self):
        assert isinstance(get_password_hasher(), Argon2PasswordHasher)

    def test_get_token_service(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
        monkeypatch.setenv("JWT_ALGORITHM", "HS256")
        monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
        monkeypatch.setenv("REFRESH_TOKEN_EXPIRE_MINUTES", "1440")
        result = get_token_service()
        assert isinstance(result, JWTTokenService)


class TestRepositoryProviders:
    async def test_get_decision_repository(self):
        mock_db = MagicMock()
        result = await get_decision_repository(mock_db)
        assert isinstance(result, MongoDecisionCurationRepository)

    async def test_get_entity_mention_repository(self):
        mock_db = MagicMock()
        result = await get_entity_mention_repository(mock_db)
        assert isinstance(result, MongoEntityMentionCurationRepository)

    async def test_get_user_action_repository(self):
        mock_db = MagicMock()
        result = await get_user_action_repository(mock_db)
        assert isinstance(result, MongoUserActionCurationRepository)

    async def test_get_statistics_repository(self):
        mock_db = MagicMock()
        result = await get_statistics_repository(mock_db)
        assert isinstance(result, MongoStatisticsRepository)


class TestUserRepository:
    async def test_get_user_repository(self):
        from ers.curation.entrypoints.api.dependencies import get_user_repository

        mock_db = MagicMock()
        result = await get_user_repository(mock_db)
        assert isinstance(result, MongoUserRepository)


class TestServiceProviders:
    async def test_get_user_action_service(self):
        mock_repo = MagicMock()
        mock_entity_repo = MagicMock()
        result = await get_user_action_service(mock_repo, mock_entity_repo)
        assert isinstance(result, UserActionService)

    async def test_get_decision_curation_service(self):
        mock_decision_repo = MagicMock()
        mock_entity_repo = MagicMock()
        mock_user_action_service = MagicMock()
        result = await get_decision_curation_service(
            mock_decision_repo, mock_entity_repo, mock_user_action_service
        )
        assert isinstance(result, DecisionCurationService)

    async def test_get_canonical_entity_service(self):
        mock_decision_repo = MagicMock()
        mock_entity_repo = MagicMock()
        result = await get_canonical_entity_service(mock_decision_repo, mock_entity_repo)
        assert isinstance(result, CanonicalEntityService)

    async def test_get_entity_service(self):
        mock_entity_repo = MagicMock()
        result = await get_entity_service(mock_entity_repo)
        assert isinstance(result, EntityService)

    async def test_get_statistics_service(self):
        mock_stats_repo = MagicMock()
        result = await get_statistics_service(mock_stats_repo)
        assert isinstance(result, StatisticsService)

    async def test_get_user_management_service(self):
        mock_user_repo = MagicMock()
        mock_hasher = MagicMock()
        result = await get_user_management_service(mock_user_repo, mock_hasher)
        assert isinstance(result, UserManagementService)

    async def test_get_auth_service(self):
        mock_user_repo = MagicMock()
        mock_hasher = MagicMock()
        mock_token_svc = MagicMock()
        result = await get_auth_service(mock_user_repo, mock_hasher, mock_token_svc)
        assert isinstance(result, AuthService)
