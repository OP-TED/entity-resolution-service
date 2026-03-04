import json

import pytest
from pymongo.asynchronous.database import AsyncDatabase


from ers.adapters.mongodb import MongoCollections, MongoEntityMentionRepository
from tests.factories import EntityMentionFactory, EntityMentionIdentifierFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(mongo_db: AsyncDatabase) -> MongoEntityMentionRepository:
    return MongoEntityMentionRepository(MongoCollections(mongo_db).entity_mentions)


class TestSaveAndFindById:
    async def test_save_and_retrieve(self, repo: MongoEntityMentionRepository) -> None:
        mention = EntityMentionFactory.build()
        await repo.save(mention)

        found = await repo.find_by_id(mention.identifiedBy)

        assert found is not None
        assert found.identifiedBy.source_id == mention.identifiedBy.source_id
        assert found.content == mention.content

    async def test_find_by_id_not_found(
        self, repo: MongoEntityMentionRepository
    ) -> None:
        missing = EntityMentionIdentifierFactory.build()
        result = await repo.find_by_id(missing)
        assert result is None


class TestFindByIdentifiers:
    async def test_batch_fetch(self, repo: MongoEntityMentionRepository) -> None:
        mentions = EntityMentionFactory.batch(3)
        for m in mentions:
            await repo.save(m)

        identifiers = [m.identifiedBy for m in mentions]
        results = await repo.find_by_identifiers(identifiers)

        assert len(results) == 3

    async def test_batch_fetch_with_limit(
        self, repo: MongoEntityMentionRepository
    ) -> None:
        mentions = EntityMentionFactory.batch(3)
        for m in mentions:
            await repo.save(m)

        identifiers = [m.identifiedBy for m in mentions]
        results = await repo.find_by_identifiers(identifiers, limit=2)

        assert len(results) == 2

    async def test_batch_fetch_partial_match(
        self, repo: MongoEntityMentionRepository
    ) -> None:
        mention = EntityMentionFactory.build()
        await repo.save(mention)

        missing = EntityMentionIdentifierFactory.build()
        results = await repo.find_by_identifiers([mention.identifiedBy, missing])

        assert len(results) == 1
        assert results[0].identifiedBy.source_id == mention.identifiedBy.source_id


class TestSearchIdentifiers:
    async def test_search_by_content_match(
        self, repo: MongoEntityMentionRepository
    ) -> None:
        mention = EntityMentionFactory.build(
            content='{"name": "Acme Corporation"}',
        )
        await repo.save(mention)

        results = await repo.search_identifiers("Acme")

        assert len(results) == 1
        assert results[0].source_id == mention.identifiedBy.source_id

    async def test_search_by_parsed_representation_match(
        self, repo: MongoEntityMentionRepository
    ) -> None:
        payload = {"name": "UniqueTestCompany", "country": "US"}
        mention = EntityMentionFactory.build(
            parsed_representation=json.dumps(payload),
        )
        await repo.save(mention)

        results = await repo.search_identifiers("UniqueTestCompany")

        assert len(results) == 1
        assert results[0].source_id == mention.identifiedBy.source_id

    async def test_search_no_match_returns_empty(
        self, repo: MongoEntityMentionRepository
    ) -> None:
        mention = EntityMentionFactory.build(
            content='{"name": "Known Entity"}',
        )
        await repo.save(mention)

        results = await repo.search_identifiers("zzzznonexistent")

        assert results == []

    async def test_search_returns_multiple_matches(
        self, repo: MongoEntityMentionRepository
    ) -> None:
        m1 = EntityMentionFactory.build(
            content='{"name": "Alpha Corp"}',
        )
        m2 = EntityMentionFactory.build(
            content='{"name": "Alpha Industries"}',
        )
        m3 = EntityMentionFactory.build(
            content='{"name": "Beta Ltd"}',
        )
        for m in [m1, m2, m3]:
            await repo.save(m)

        results = await repo.search_identifiers("Alpha")

        assert len(results) == 2
