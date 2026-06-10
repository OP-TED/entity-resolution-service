"""Step definitions for cluster_sizes_projection.feature.

Tests the cluster_sizes projection invariants at the service layer.
Mocks both the decision repository and the ClusterSizeIndex so that
real DecisionStoreService logic is exercised without touching MongoDB.
"""
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, create_autospec

from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from pytest_bdd import given, parsers, scenario, then, when

from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository
from ers.resolution_decision_store.domain.cluster_size_index import ClusterSizeIndex
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

FEATURE = str(Path(__file__).resolve().parent / "cluster_sizes_projection.feature")


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE, "New decision integration increments the destination cluster")
def test_new_decision_increments_cluster():
    pass


@scenario(FEATURE, "Placement change shifts the count atomically")
def test_placement_change_shifts_counts():
    pass


@scenario(FEATURE, "Unchanged placement is a no-op")
def test_unchanged_placement_is_noop():
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_identifier() -> EntityMentionIdentifier:
    return EntityMentionIdentifier(source_id="s1", request_id="r1", entity_type="Person")


def make_cluster(cluster_id: str) -> ClusterReference:
    return ClusterReference(cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85)


def make_decision(cluster_id: str, now: datetime | None = None) -> Decision:
    ts = now or datetime.now(UTC)
    return Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster(cluster_id),
        candidates=[],
        created_at=ts,
        updated_at=ts,
    )


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(parsers.parse('cluster "{cluster_id}" has size {size:d} in cluster_sizes'))
def step_cluster_has_size(ctx: dict[str, Any], cluster_id: str, size: int) -> None:
    """Initialise the in-memory cluster_sizes projection tracking."""
    if "cluster_sizes" not in ctx:
        ctx["cluster_sizes"] = {}
    ctx["cluster_sizes"][cluster_id] = size


@given(parsers.parse('a decision is currently placed in cluster "{cluster_id}"'))
def step_decision_in_cluster(ctx: dict[str, Any], cluster_id: str) -> None:
    """Record the existing decision placement for use in When steps."""
    ctx["existing_cluster_id"] = cluster_id


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(parsers.parse('ERE integrates a new decision with current_placement cluster_id "{cluster_id}"'))
def step_ere_integrates_new_decision(ctx: dict[str, Any], cluster_id: str) -> None:
    """Simulate an insert-path call to DecisionStoreService.store_decision."""
    now = datetime.now(UTC)
    result_decision = make_decision(cluster_id, now)

    mock_repo = create_autospec(MongoDecisionRepository, instance=True)
    mock_repo.find_by_triad.return_value = None  # No existing decision → insert path
    mock_repo.upsert_decision.return_value = result_decision

    mock_index = AsyncMock(spec=ClusterSizeIndex)

    svc = DecisionStoreService(repository=mock_repo, cluster_size_index=mock_index)
    asyncio.run(
        svc.store_decision(make_identifier(), make_cluster(cluster_id), [], now)
    )

    ctx["mock_index"] = mock_index
    ctx["result_decision"] = result_decision
    ctx["integrated_cluster_id"] = cluster_id


@when(parsers.parse('ERE re-integrates that decision with cluster_id "{new_cluster_id}"'))
def step_ere_reintegrates_decision(ctx: dict[str, Any], new_cluster_id: str) -> None:
    """Simulate an update-path (or no-op) call to DecisionStoreService.store_decision."""
    now = datetime.now(UTC)
    old_cluster_id: str = ctx["existing_cluster_id"]
    existing_decision = make_decision(old_cluster_id, now)
    result_decision = make_decision(new_cluster_id, now)

    mock_repo = create_autospec(MongoDecisionRepository, instance=True)
    mock_repo.find_by_triad.return_value = existing_decision
    mock_repo.upsert_decision.return_value = result_decision

    mock_index = AsyncMock(spec=ClusterSizeIndex)

    svc = DecisionStoreService(repository=mock_repo, cluster_size_index=mock_index)
    asyncio.run(
        svc.store_decision(make_identifier(), make_cluster(new_cluster_id), [], now)
    )

    ctx["mock_index"] = mock_index
    ctx["old_cluster_id"] = old_cluster_id
    ctx["new_cluster_id"] = new_cluster_id


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.parse('cluster_sizes["{cluster_id}"] size is {expected_size:d}'))
def step_cluster_size_is(ctx: dict[str, Any], cluster_id: str, expected_size: int) -> None:
    """Verify that shift() was called with the correct arguments to produce expected_size."""
    mock_index: AsyncMock = ctx["mock_index"]
    initial_size: int = ctx.get("cluster_sizes", {}).get(cluster_id, 0)

    # Collect all shift calls to determine the net delta applied to this cluster
    net_delta = 0
    for call in mock_index.shift.call_args_list:
        kwargs = call.kwargs
        by = kwargs.get("by", 1)
        if kwargs.get("to_cluster") == cluster_id:
            net_delta += by
        if kwargs.get("from_cluster") == cluster_id:
            net_delta -= by

    actual_projected_size = initial_size + net_delta
    assert actual_projected_size == expected_size, (
        f"cluster_sizes[{cluster_id!r}]: expected {expected_size}, "
        f"got {actual_projected_size} "
        f"(initial={initial_size}, net_delta={net_delta}, "
        f"shift_calls={mock_index.shift.call_args_list})"
    )
