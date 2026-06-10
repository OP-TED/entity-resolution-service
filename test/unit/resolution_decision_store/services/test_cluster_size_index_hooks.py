"""Unit tests for ClusterSizeIndex hook integration in DecisionStoreService.

Verifies that store_decision() correctly calls ClusterSizeIndex.shift() for:
  - Insert path (new decision, no prior cluster)
  - Update path with changed cluster
  - Update path with unchanged cluster (no-op)
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository
from ers.resolution_decision_store.domain.cluster_size_index import ClusterSizeIndex
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService


def make_identifier() -> EntityMentionIdentifier:
    return EntityMentionIdentifier(source_id="s1", request_id="r1", entity_type="Person")


def make_cluster(cluster_id: str = "c1") -> ClusterReference:
    return ClusterReference(cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85)


def make_decision(cluster_id: str = "c1", now: datetime | None = None) -> Decision:
    ts = now or datetime.now(UTC)
    return Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster(cluster_id),
        candidates=[],
        created_at=ts,
        updated_at=ts,
    )


def make_service(
    existing: Decision | None,
    upsert_result: Decision,
) -> tuple[DecisionStoreService, AsyncMock, AsyncMock]:
    """Return (service, mock_repo, mock_index)."""
    mock_repo = create_autospec(MongoDecisionRepository, instance=True)
    mock_repo.find_by_triad.return_value = existing
    mock_repo.upsert_decision.return_value = upsert_result

    mock_index = AsyncMock(spec=ClusterSizeIndex)

    svc = DecisionStoreService(repository=mock_repo, cluster_size_index=mock_index)
    return svc, mock_repo, mock_index


# ---------------------------------------------------------------------------
# Insert path (no prior doc)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_path_calls_shift_with_from_none():
    """New decision → shift(from=None, to=new_cluster_id)."""
    now = datetime.now(UTC)
    result_decision = make_decision("c1", now)
    svc, _, mock_index = make_service(existing=None, upsert_result=result_decision)

    await svc.store_decision(make_identifier(), make_cluster("c1"), [], now)

    mock_index.shift.assert_awaited_once_with(from_cluster=None, to_cluster="c1")


# ---------------------------------------------------------------------------
# Update path — placement changed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_path_changed_cluster_calls_shift_from_old_to_new():
    """Placement change → shift(from=old_cluster_id, to=new_cluster_id)."""
    now = datetime.now(UTC)
    existing = make_decision("c1", now)
    result_decision = make_decision("c2", now)
    svc, _, mock_index = make_service(existing=existing, upsert_result=result_decision)

    await svc.store_decision(make_identifier(), make_cluster("c2"), [], now)

    mock_index.shift.assert_awaited_once_with(from_cluster="c1", to_cluster="c2")


# ---------------------------------------------------------------------------
# Update path — placement unchanged (no-op)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unchanged_placement_does_not_call_shift():
    """Same cluster_id re-write → shift is NOT called (short-circuit)."""
    now = datetime.now(UTC)
    existing = make_decision("c1", now)
    # upsert_decision should not be called, so result doesn't matter
    svc, _, mock_index = make_service(existing=existing, upsert_result=existing)

    await svc.store_decision(make_identifier(), make_cluster("c1"), [], now)

    mock_index.shift.assert_not_awaited()


# ---------------------------------------------------------------------------
# No ClusterSizeIndex injected — backward-compat (index=None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_decision_works_without_cluster_size_index():
    """DecisionStoreService must work when cluster_size_index is not provided."""
    now = datetime.now(UTC)
    mock_repo = create_autospec(MongoDecisionRepository, instance=True)
    mock_repo.find_by_triad.return_value = None
    mock_repo.upsert_decision.return_value = make_decision("c1", now)

    # No index — default None
    svc = DecisionStoreService(repository=mock_repo)

    # Must not raise
    result = await svc.store_decision(make_identifier(), make_cluster("c1"), [], now)
    assert result.current_placement.cluster_id == "c1"
