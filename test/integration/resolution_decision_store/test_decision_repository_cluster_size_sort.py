"""Integration test for the cluster-size ordering path of find_with_filters.

This path runs an aggregation (``$lookup`` on ``cluster_sizes``) and, like the
review-filter path, requires the async cursor to be awaited. It had no real-engine
coverage before; this test exercises it against FerretDB.
"""
from datetime import UTC, datetime

import pytest
from erspec.models.core import ClusterReference, EntityMentionIdentifier

from ers.commons.domain.data_transfer_objects import (
    CursorParams,
    DecisionFilters,
    DecisionOrdering,
)
from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository

_T0 = datetime(2026, 6, 2, 12, 0, 0, tzinfo=UTC)


def _ident(source_id: str) -> EntityMentionIdentifier:
    return EntityMentionIdentifier(source_id=source_id, request_id="r1", entity_type="Person")


def _cluster(cluster_id: str) -> ClusterReference:
    return ClusterReference(cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.8)


@pytest.fixture()
async def repo(mongo_db):
    r = MongoDecisionRepository(mongo_db)
    await r.ensure_indexes()
    return r


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cluster_size_descending_orders_by_size(repo, mongo_db):
    # Decisions placed in clusters of different sizes.
    await repo.upsert_decision(_ident("s-A"), _cluster("A"), [], _T0)
    await repo.upsert_decision(_ident("s-B"), _cluster("B"), [], _T0)
    await repo.upsert_decision(_ident("s-C"), _cluster("C"), [], _T0)
    await mongo_db["cluster_sizes"].insert_many(
        [
            {"_id": "A", "size": 3},
            {"_id": "B", "size": 1},
            {"_id": "C", "size": 2},
        ]
    )

    page = await repo.find_with_filters(
        filters=DecisionFilters(ordering=DecisionOrdering.CLUSTER_SIZE_DESC),
        cursor_params=CursorParams(limit=50),
    )

    placements = [d.current_placement.cluster_id for d in page.results]
    assert placements == ["A", "C", "B"]
