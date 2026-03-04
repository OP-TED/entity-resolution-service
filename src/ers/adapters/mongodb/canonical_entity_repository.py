from erspec.models.core import CanonicalEntityIdentifier

from ers.adapters.mongodb.base import BaseMongoRepository
from ers.application.ports.canonical_entity_repository import (
    CanonicalEntityRepository as CanonicalEntityRepositoryPort,
)


class MongoCanonicalEntityRepository(
    BaseMongoRepository[CanonicalEntityIdentifier, str],
    CanonicalEntityRepositoryPort,
):
    _model_class = CanonicalEntityIdentifier
    _id_field = "identifier"
