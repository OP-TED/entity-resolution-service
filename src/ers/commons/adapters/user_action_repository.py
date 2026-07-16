from erspec.models.core import UserAction

from ers.commons.adapters.repository import (
    AsyncReadRepository,
    AsyncWriteRepository,
    BaseMongoRepository,
)


class UserActionRepository(
    AsyncReadRepository[UserAction, str], AsyncWriteRepository[UserAction, str]
):
    """Repository for persisting user action (curation) entries."""


class MongoUserActionRepository(
    BaseMongoRepository[UserAction, str],
    UserActionRepository,
):
    _model_class = UserAction
    _id_field = "id"
    _collection_name = "user_actions"
