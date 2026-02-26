from typing import Annotated

from fastapi import Depends

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


# Repository providers


async def get_decision_repository() -> DecisionRepository:
    raise NotImplementedError("Decision repository adapter not configured")


async def get_entity_mention_repository() -> EntityMentionRepository:
    raise NotImplementedError("EntityMention repository adapter not configured")


async def get_canonical_entity_repository() -> CanonicalEntityRepository:
    raise NotImplementedError("CanonicalEntity repository adapter not configured")


async def get_user_action_repository() -> UserActionRepository:
    raise NotImplementedError("UserAction repository adapter not configured")


async def get_statistics_repository() -> StatisticsRepository:
    raise NotImplementedError("Statistics repository adapter not configured")


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
