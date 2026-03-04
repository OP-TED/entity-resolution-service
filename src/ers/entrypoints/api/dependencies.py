from typing import Annotated

from fastapi import Depends, Request
from pymongo.asynchronous.database import AsyncDatabase

from ers.adapters.mongodb import (
    MongoCanonicalEntityRepository,
    MongoCollections,
    MongoDecisionRepository,
    MongoEntityMentionRepository,
    MongoStatisticsRepository,
    MongoUserActionRepository,
)
from ers.application.ports.canonical_entity_repository import (
    CanonicalEntityRepository,
)
from ers.application.ports.decision_repository import DecisionRepository
from ers.application.ports.entity_mention_repository import EntityMentionRepository
from ers.application.ports.statistics_repository import StatisticsRepository
from ers.application.ports.user_action_repository import UserActionRepository
from ers.application.services import (
    CanonicalEntityService,
    DecisionCurationService,
    EntityService,
    StatisticsService,
    UserActionService,
)


def _get_database(request: Request) -> AsyncDatabase:
    return request.app.state.mongo_db


def _get_collections(request: Request) -> MongoCollections:
    return MongoCollections(_get_database(request))


# Repository providers


async def get_decision_repository(
    collections: Annotated[MongoCollections, Depends(_get_collections)],
) -> DecisionRepository:
    return MongoDecisionRepository(collections.decisions)


async def get_entity_mention_repository(
    collections: Annotated[MongoCollections, Depends(_get_collections)],
) -> EntityMentionRepository:
    return MongoEntityMentionRepository(collections.entity_mentions)


async def get_canonical_entity_repository(
    collections: Annotated[MongoCollections, Depends(_get_collections)],
) -> CanonicalEntityRepository:
    return MongoCanonicalEntityRepository(collections.canonical_entities)


async def get_user_action_repository(
    collections: Annotated[MongoCollections, Depends(_get_collections)],
) -> UserActionRepository:
    return MongoUserActionRepository(collections.user_actions)


async def get_statistics_repository(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> StatisticsRepository:
    return MongoStatisticsRepository(db)


# Service providers


async def get_user_action_service(
    repo: Annotated[UserActionRepository, Depends(get_user_action_repository)],
) -> UserActionService:
    return UserActionService(user_action_repository=repo)


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
    canonical_repo: Annotated[
        CanonicalEntityRepository, Depends(get_canonical_entity_repository)
    ],
    entity_repo: Annotated[
        EntityMentionRepository, Depends(get_entity_mention_repository)
    ],
) -> CanonicalEntityService:
    return CanonicalEntityService(
        decision_repository=decision_repo,
        canonical_entity_repository=canonical_repo,
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
