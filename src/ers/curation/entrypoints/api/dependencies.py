from typing import Annotated

from fastapi import Depends, Request
from pymongo.asynchronous.database import AsyncDatabase

from ers import config
from ers.commons.adapters.hasher import Argon2PasswordHasher, ContentHasher
from ers.curation.adapters import (
    DecisionCurationRepository,
    EntityMentionCurationRepository,
    MongoDecisionCurationRepository,
    MongoEntityMentionCurationRepository,
    MongoStatisticsRepository,
    MongoUserActionCurationRepository,
    StatisticsRepository,
    UserActionCurationRepository,
)
from ers.curation.services import (
    CanonicalEntityService,
    DecisionCurationService,
    EntityService,
    StatisticsService,
    UserActionService,
)
from ers.users.adapters import MongoUserRepository, UserRepository
from ers.users.services import AuthService, UserManagementService
from ers.users.services.token_service import JWTTokenService, TokenService


def _get_database(request: Request) -> AsyncDatabase:
    return request.app.state.mongo_db


# Infrastructure providers


def get_password_hasher() -> ContentHasher:
    return Argon2PasswordHasher()


def get_token_service() -> TokenService:
    return JWTTokenService(
        secret_key=config.JWT_SECRET_KEY,
        algorithm=config.JWT_ALGORITHM,
        access_expire_minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES,
        refresh_expire_minutes=config.REFRESH_TOKEN_EXPIRE_MINUTES,
    )


# Repository providers


async def get_decision_repository(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> DecisionCurationRepository:
    return MongoDecisionCurationRepository(db)


async def get_entity_mention_repository(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> EntityMentionCurationRepository:
    return MongoEntityMentionCurationRepository(db)


async def get_user_action_repository(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> UserActionCurationRepository:
    return MongoUserActionCurationRepository(db)


async def get_statistics_repository(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> StatisticsRepository:
    return MongoStatisticsRepository(db)


async def get_user_repository(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> UserRepository:
    return MongoUserRepository(db)


# Service providers


async def get_user_action_service(
    repo: Annotated[UserActionCurationRepository, Depends(get_user_action_repository)],
    entity_repo: Annotated[EntityMentionCurationRepository, Depends(get_entity_mention_repository)],
) -> UserActionService:
    return UserActionService(
        user_action_repository=repo,
        entity_mention_repository=entity_repo,
    )


async def get_decision_curation_service(
    decision_repo: Annotated[DecisionCurationRepository, Depends(get_decision_repository)],
    entity_repo: Annotated[EntityMentionCurationRepository, Depends(get_entity_mention_repository)],
    user_action_service: Annotated[UserActionService, Depends(get_user_action_service)],
) -> DecisionCurationService:
    return DecisionCurationService(
        decision_repository=decision_repo,
        entity_mention_repository=entity_repo,
        user_action_service=user_action_service,
    )


async def get_canonical_entity_service(
    decision_repo: Annotated[DecisionCurationRepository, Depends(get_decision_repository)],
    entity_repo: Annotated[EntityMentionCurationRepository, Depends(get_entity_mention_repository)],
) -> CanonicalEntityService:
    return CanonicalEntityService(
        decision_repository=decision_repo,
        entity_mention_repository=entity_repo,
    )


async def get_entity_service(
    entity_repo: Annotated[EntityMentionCurationRepository, Depends(get_entity_mention_repository)],
) -> EntityService:
    return EntityService(entity_mention_repository=entity_repo)


async def get_statistics_service(
    stats_repo: Annotated[StatisticsRepository, Depends(get_statistics_repository)],
) -> StatisticsService:
    return StatisticsService(statistics_repository=stats_repo)


async def get_auth_service(
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    hasher: Annotated[ContentHasher, Depends(get_password_hasher)],
    token_svc: Annotated[TokenService, Depends(get_token_service)],
) -> AuthService:
    return AuthService(
        user_repository=user_repo,
        password_hasher=hasher,
        token_service=token_svc,
    )


async def get_user_management_service(
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    hasher: Annotated[ContentHasher, Depends(get_password_hasher)],
) -> UserManagementService:
    return UserManagementService(user_repository=user_repo, password_hasher=hasher)
