import json

import pytest
from pymongo.asynchronous.database import AsyncDatabase

from ers.curation.adapters.entity_mention_repository import (
    MongoEntityMentionCurationRepository,
)
from tests.unit.factories import (
    EntityMentionIdentifierFactory,
    ResolutionRequestRecordFactory,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(mongo_db: AsyncDatabase) -> MongoEntityMentionCurationRepository:
    return MongoEntityMentionCurationRepository(mongo_db)


class TestSaveAndFindById:
    async def test_save_and_retrieve(self, repo: MongoEntityMentionCurationRepository) -> None:
        record = ResolutionRequestRecordFactory.build()
        await repo.store(record)

        found = await repo.find_by_id(repo._triad_id(record.identifiedBy))

        assert found is not None
        assert found.identifiedBy.source_id == record.identifiedBy.source_id
        assert found.content == record.content

    async def test_find_by_id_not_found(self, repo: MongoEntityMentionCurationRepository) -> None:
        missing = EntityMentionIdentifierFactory.build()
        result = await repo.find_by_id(repo._triad_id(missing))
        assert result is None


class TestFindByIdentifiers:
    async def test_batch_fetch(self, repo: MongoEntityMentionCurationRepository) -> None:
        records = ResolutionRequestRecordFactory.batch(3)
        for r in records:
            await repo.store(r)

        identifiers = [r.identifiedBy for r in records]
        results = await repo.find_by_identifiers(identifiers)

        assert len(results) == 3

    async def test_batch_fetch_with_limit(self, repo: MongoEntityMentionCurationRepository) -> None:
        records = ResolutionRequestRecordFactory.batch(3)
        for r in records:
            await repo.store(r)

        identifiers = [r.identifiedBy for r in records]
        results = await repo.find_by_identifiers(identifiers, limit=2)

        assert len(results) == 2

    async def test_batch_fetch_partial_match(
        self, repo: MongoEntityMentionCurationRepository
    ) -> None:
        record = ResolutionRequestRecordFactory.build()
        await repo.store(record)

        missing = EntityMentionIdentifierFactory.build()
        results = await repo.find_by_identifiers([record.identifiedBy, missing])

        assert len(results) == 1
        assert results[0].identifiedBy.source_id == record.identifiedBy.source_id


class TestSearchIdentifiers:
    async def test_search_by_content_match(
        self, repo: MongoEntityMentionCurationRepository
    ) -> None:
        record = ResolutionRequestRecordFactory.build(
            content='{"name": "Acme Corporation"}',
        )
        await repo.store(record)

        results = await repo.search_identifiers("Acme")

        assert len(results) == 1
        assert results[0].source_id == record.identifiedBy.source_id

    async def test_search_by_parsed_representation_match(
        self, repo: MongoEntityMentionCurationRepository
    ) -> None:
        payload = {"name": "UniqueTestCompany", "country": "US"}
        record = ResolutionRequestRecordFactory.build(
            parsed_representation=json.dumps(payload),
        )
        await repo.store(record)

        results = await repo.search_identifiers("UniqueTestCompany")

        assert len(results) == 1
        assert results[0].source_id == record.identifiedBy.source_id

    async def test_search_no_match_returns_empty(
        self, repo: MongoEntityMentionCurationRepository
    ) -> None:
        record = ResolutionRequestRecordFactory.build(
            content='{"name": "Known Entity"}',
        )
        await repo.store(record)

        results = await repo.search_identifiers("zzzznonexistent")

        assert results == []

    async def test_search_returns_multiple_matches(
        self, repo: MongoEntityMentionCurationRepository
    ) -> None:
        m1 = ResolutionRequestRecordFactory.build(
            content='{"name": "Alpha Corp"}',
        )
        m2 = ResolutionRequestRecordFactory.build(
            content='{"name": "Alpha Industries"}',
        )
        m3 = ResolutionRequestRecordFactory.build(
            content='{"name": "Beta Ltd"}',
        )
        for r in [m1, m2, m3]:
            await repo.store(r)

        results = await repo.search_identifiers("Alpha")

        assert len(results) == 2
