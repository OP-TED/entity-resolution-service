from datetime import datetime

from erspec.models.core import EntityMentionIdentifier, UserAction

from ers.adapters.mongodb.base import BaseMongoRepository
from ers.application.ports.user_action_repository import (
    UserActionRepository as UserActionRepositoryPort,
)


class MongoUserActionRepository(
    BaseMongoRepository[UserAction, str],
    UserActionRepositoryPort,
):
    _model_class = UserAction
    _id_field = "id"

    async def has_current_action(
        self,
        about_entity_mention: EntityMentionIdentifier,
        since: datetime,
    ) -> bool:
        count = await self._collection.count_documents(
            {
                "about_entity_mention": about_entity_mention.model_dump(mode="python"),
                "created_at": {"$gte": since},
            },
            limit=1,
        )
        return count > 0
