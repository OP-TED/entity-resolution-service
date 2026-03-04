from datetime import datetime, timezone

import pytest
from pymongo.asynchronous.database import AsyncDatabase

from erspec.models.core import Decision

from ers.adapters.mongodb import MongoCollections, MongoDecisionRepository
from ers.application.dtos import DecisionFilters, DecisionOrdering, PaginationParams
from tests.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
    EntityMentionIdentifierFactory,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(mongo_db: AsyncDatabase) -> MongoDecisionRepository:
    return MongoDecisionRepository(MongoCollections(mongo_db).decisions)


class TestSaveAndFindById:
    async def test_save_and_retrieve(self, repo: MongoDecisionRepository) -> None:
        decision = DecisionFactory.build()
        await repo.save(decision)

        found = await repo.find_by_id(decision.id)

        assert found is not None
        assert found.id == decision.id
        assert (
            found.about_entity_mention.source_id
            == decision.about_entity_mention.source_id
        )

    async def test_find_by_id_not_found(self, repo: MongoDecisionRepository) -> None:
        result = await repo.find_by_id("nonexistent")
        assert result is None

    async def test_save_upserts_on_same_id(self, repo: MongoDecisionRepository) -> None:
        decision = DecisionFactory.build()
        await repo.save(decision)

        updated = Decision(
            id=decision.id,
            about_entity_mention=decision.about_entity_mention,
            current_placement=decision.current_placement,
            candidates=decision.candidates,
            created_at=decision.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        await repo.save(updated)

        found = await repo.find_by_id(decision.id)
        assert found is not None
        assert found.updated_at is not None


class TestFindWithFilters:
    async def _seed(self, repo: MongoDecisionRepository) -> list[Decision]:
        decisions = [
            DecisionFactory.build(
                id="d-1",
                about_entity_mention=EntityMentionIdentifierFactory.build(
                    entity_type="ORGANISATION"
                ),
                current_placement=ClusterReferenceFactory.build(
                    confidence_score=0.95, similarity_score=0.90
                ),
            ),
            DecisionFactory.build(
                id="d-2",
                about_entity_mention=EntityMentionIdentifierFactory.build(
                    entity_type="ORGANISATION"
                ),
                current_placement=ClusterReferenceFactory.build(
                    confidence_score=0.60, similarity_score=0.55
                ),
            ),
            DecisionFactory.build(
                id="d-3",
                about_entity_mention=EntityMentionIdentifierFactory.build(
                    entity_type="PROCEDURE"
                ),
                current_placement=ClusterReferenceFactory.build(
                    confidence_score=0.80, similarity_score=0.75
                ),
            ),
        ]
        for d in decisions:
            await repo.save(d)
        return decisions

    async def test_no_filters_returns_all(self, repo: MongoDecisionRepository) -> None:
        await self._seed(repo)
        result = await repo.find_with_filters(DecisionFilters(), PaginationParams())
        assert result.count == 3

    async def test_filter_by_entity_type(self, repo: MongoDecisionRepository) -> None:
        await self._seed(repo)
        result = await repo.find_with_filters(
            DecisionFilters(entity_type="ORGANISATION"), PaginationParams()
        )
        assert result.count == 2
        assert all(
            r.about_entity_mention.entity_type == "ORGANISATION" for r in result.results
        )

    async def test_filter_by_confidence_range(
        self, repo: MongoDecisionRepository
    ) -> None:
        await self._seed(repo)
        result = await repo.find_with_filters(
            DecisionFilters(confidence_min=0.70, confidence_max=0.99),
            PaginationParams(),
        )
        assert all(
            0.70 <= r.current_placement.confidence_score <= 0.99 for r in result.results
        )

    async def test_pagination(self, repo: MongoDecisionRepository) -> None:
        await self._seed(repo)
        page1 = await repo.find_with_filters(
            DecisionFilters(), PaginationParams(page=1, per_page=2)
        )
        assert len(page1.results) == 2
        assert page1.next == 2
        assert page1.previous is None

        page2 = await repo.find_with_filters(
            DecisionFilters(), PaginationParams(page=2, per_page=2)
        )
        assert len(page2.results) == 1
        assert page2.next is None
        assert page2.previous == 1

    async def test_ordering_by_confidence_asc(
        self, repo: MongoDecisionRepository
    ) -> None:
        await self._seed(repo)
        result = await repo.find_with_filters(
            DecisionFilters(ordering=DecisionOrdering.CONFIDENCE_ASC),
            PaginationParams(),
        )
        scores = [r.current_placement.confidence_score for r in result.results]
        assert scores == sorted(scores)

    async def test_filter_by_mention_identifiers(
        self, repo: MongoDecisionRepository
    ) -> None:
        decisions = await self._seed(repo)
        target = decisions[0].about_entity_mention

        result = await repo.find_with_filters(
            DecisionFilters(),
            PaginationParams(),
            mention_identifiers=[target],
        )

        assert result.count == 1
        assert result.results[0].id == decisions[0].id

    async def test_filter_by_mention_identifiers_empty_list_returns_none(
        self, repo: MongoDecisionRepository
    ) -> None:
        await self._seed(repo)

        result = await repo.find_with_filters(
            DecisionFilters(),
            PaginationParams(),
            mention_identifiers=[],
        )

        assert result.count == 0
        assert result.results == []
