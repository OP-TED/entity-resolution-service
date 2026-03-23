from erspec.models.core import Decision

from ers.commons.adapters.repository import (
    AsyncReadRepository,
    AsyncWriteRepository,
    BaseMongoRepository,
)


class DecisionRepository(
    AsyncReadRepository[Decision, str],
    AsyncWriteRepository[Decision, str],
):
    """Repository for decision projection persistence and querying."""


class MongoDecisionRepository(
    BaseMongoRepository[Decision, str],
    DecisionRepository,
):
    _model_class = Decision
    _id_field = "id"
    _collection_name = "decisions"
