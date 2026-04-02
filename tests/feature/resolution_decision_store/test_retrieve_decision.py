"""Step definitions for: retrieve_decision.feature"""
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from pytest_bdd import given, scenario, then, when

from ers.resolution_decision_store.services.decision_store_service import get_decision_by_triad

FEATURE_FILE = str(Path(__file__).parent / "retrieve_decision.feature")


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE_FILE, "Finding an existing decision by triad")
def test_finding_existing_decision():
    pass


@scenario(FEATURE_FILE, "Looking up a non-existent triad returns None")
def test_looking_up_nonexistent_triad():
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_identifier(source_id="s1", request_id="r1", entity_type="Person"):
    return EntityMentionIdentifier(
        source_id=source_id, request_id=request_id, entity_type=entity_type
    )


def make_cluster(cluster_id="c1"):
    return ClusterReference(
        cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85
    )


def make_decision(now, cluster_id="c1"):
    return Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster(cluster_id),
        candidates=[],
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("a stored decision for a known triad")
def step_stored_decision(ctx, mock_repo):
    ctx["identifier"] = make_identifier()
    now = datetime.now(UTC)
    ctx["stored_decision"] = make_decision(now)
    mock_repo.find_by_triad = AsyncMock(return_value=ctx["stored_decision"])


@given("an empty decision store")
def step_empty_store(ctx, mock_repo):
    ctx["identifier"] = make_identifier(source_id="unknown")
    mock_repo.find_by_triad = AsyncMock(return_value=None)


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("I look up the decision by that triad")
def step_lookup_by_triad(ctx, service):
    try:
        ctx["result"] = asyncio.run(
            get_decision_by_triad(ctx["identifier"], service=service)
        )
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when("I look up a decision by an unknown triad")
def step_lookup_unknown_triad(ctx, service):
    try:
        ctx["result"] = asyncio.run(
            get_decision_by_triad(ctx["identifier"], service=service)
        )
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the returned record matches the stored decision")
def step_record_matches_stored(ctx):
    assert ctx["raised_exception"] is None, ctx["raised_exception"]
    assert isinstance(ctx["result"], Decision)
    assert ctx["result"].id == ctx["stored_decision"].id
    assert ctx["result"].current_placement == ctx["stored_decision"].current_placement


@then("the result is None")
def step_result_is_none(ctx):
    assert ctx["raised_exception"] is None, ctx["raised_exception"]
    assert ctx["result"] is None
