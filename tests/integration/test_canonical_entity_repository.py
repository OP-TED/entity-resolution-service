import pytest
from pymongo.asynchronous.database import AsyncDatabase

from ers.adapters.mongodb import MongoCanonicalEntityRepository, MongoCollections
from tests.factories import CanonicalEntityIdentifierFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(mongo_db: AsyncDatabase) -> MongoCanonicalEntityRepository:
    return MongoCanonicalEntityRepository(MongoCollections(mongo_db).canonical_entities)


class TestSaveAndFindById:
    async def test_save_and_retrieve(
        self, repo: MongoCanonicalEntityRepository
    ) -> None:
        entity = CanonicalEntityIdentifierFactory.build()
        await repo.save(entity)

        found = await repo.find_by_id(entity.identifier)

        assert found is not None
        assert found.identifier == entity.identifier
        assert len(found.equivalent_to) == len(entity.equivalent_to)

    async def test_find_by_id_not_found(
        self, repo: MongoCanonicalEntityRepository
    ) -> None:
        result = await repo.find_by_id("nonexistent")
        assert result is None
