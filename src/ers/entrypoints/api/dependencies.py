from typing import Annotated

from fastapi import Depends, Request
from pymongo.asynchronous.database import AsyncDatabase

from ers.adapters.argon2_hasher import Argon2PasswordHasher
from ers.adapters.jwt_token_service import JWTTokenService
from ers.adapters.mongodb import (
    MongoCollections,
    MongoDecisionRepository,
    MongoEntityMentionRepository,
    MongoStatisticsRepository,
    MongoUserActionRepository,
    MongoUserRepository,
)
from ers.application.ports.decision_repository import DecisionRepository
from ers.application.ports.entity_mention_repository import EntityMentionRepository
from ers.application.ports.password_hasher import PasswordHasher
from ers.application.ports.statistics_repository import StatisticsRepository
from ers.application.ports.token_service import TokenService
from ers.application.ports.user_action_repository import UserActionRepository
from ers.application.ports.user_repository import UserRepository
from ers.application.services import (
    AuthService,
    CanonicalEntityService,
    DecisionCurationService,
    EntityService,
    StatisticsService,
    UserActionService,
    UserManagementService,
)
from ers.config import Settings, get_settings


def _get_database(request: Request) -> AsyncDatabase:
    return request.app.state.mongo_db


def _get_collections(request: Request) -> MongoCollections:
    return MongoCollections(_get_database(request))


# Infrastructure providers


def get_password_hasher() -> PasswordHasher:
    return Argon2PasswordHasher()


def get_token_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenService:
    return JWTTokenService(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        access_expire_minutes=settings.access_token_expire_minutes,
        refresh_expire_minutes=settings.refresh_token_expire_minutes,
    )


# Repository providers


async def get_decision_repository(
    collections: Annotated[MongoCollections, Depends(_get_collections)],
) -> DecisionRepository:
    return MongoDecisionRepository(collections.decisions)


async def get_entity_mention_repository(
    collections: Annotated[MongoCollections, Depends(_get_collections)],
) -> EntityMentionRepository:
    return MongoEntityMentionRepository(collections.entity_mentions)


async def get_user_action_repository(
    collections: Annotated[MongoCollections, Depends(_get_collections)],
) -> UserActionRepository:
    return MongoUserActionRepository(collections.user_actions)


async def get_statistics_repository(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> StatisticsRepository:
    return MongoStatisticsRepository(db)


async def get_user_repository(
    collections: Annotated[MongoCollections, Depends(_get_collections)],
) -> UserRepository:
    return MongoUserRepository(collections.users)


# Service providers


async def get_user_action_service(
    repo: Annotated[UserActionRepository, Depends(get_user_action_repository)],
    entity_repo: Annotated[
        EntityMentionRepository, Depends(get_entity_mention_repository)
    ],
) -> UserActionService:
    return UserActionService(
        user_action_repository=repo,
        entity_mention_repository=entity_repo,
    )


async def get_decision_curation_service(
    decision_repo: Annotated[DecisionRepository, Depends(get_decision_repository)],
    entity_repo: Annotated[
        EntityMentionRepository, Depends(get_entity_mention_repository)
    ],
    user_action_service: Annotated[UserActionService, Depends(get_user_action_service)],
) -> DecisionCurationService:
    return DecisionCurationService(
        decision_repository=decision_repo,
        entity_mention_repository=entity_repo,
        user_action_service=user_action_service,
    )


async def get_canonical_entity_service(
    decision_repo: Annotated[DecisionRepository, Depends(get_decision_repository)],
    entity_repo: Annotated[
        EntityMentionRepository, Depends(get_entity_mention_repository)
    ],
) -> CanonicalEntityService:
    return CanonicalEntityService(
        decision_repository=decision_repo,
        entity_mention_repository=entity_repo,
    )


async def get_entity_service(
    entity_repo: Annotated[
        EntityMentionRepository, Depends(get_entity_mention_repository)
    ],
) -> EntityService:
    return EntityService(entity_mention_repository=entity_repo)


async def get_statistics_service(
    stats_repo: Annotated[StatisticsRepository, Depends(get_statistics_repository)],
) -> StatisticsService:
    return StatisticsService(statistics_repository=stats_repo)


async def get_auth_service(
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    token_svc: Annotated[TokenService, Depends(get_token_service)],
) -> AuthService:
    return AuthService(
        user_repository=user_repo,
        password_hasher=hasher,
        token_service=token_svc,
    )


async def get_user_management_service(
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
) -> UserManagementService:
    return UserManagementService(user_repository=user_repo, password_hasher=hasher)
