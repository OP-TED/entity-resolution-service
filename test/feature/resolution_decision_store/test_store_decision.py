"""Step definitions for: store_decision.feature"""
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from pytest_bdd import given, parsers, scenario, then, when

from ers import config
from ers.resolution_decision_store.domain.errors import StaleOutcomeError
from ers.resolution_decision_store.services.decision_store_service import store_decision

FEATURE_FILE = str(Path(__file__).parent / "store_decision.feature")


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE_FILE, "Storing a new decision succeeds")
def test_storing_new_decision_succeeds():
    pass


@scenario(FEATURE_FILE, "Replacing a decision with a newer timestamp succeeds")
def test_replacing_decision_with_newer_timestamp():
    pass


@scenario(FEATURE_FILE, "Stale outcome is rejected")
def test_stale_outcome_rejected():
    pass


@scenario(FEATURE_FILE, "Candidates are truncated to max_candidates")
def test_candidates_truncated():
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


def make_decision(now, cluster_id="c1", candidates=None):
    return Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster(cluster_id),
        candidates=candidates or [],
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("a valid entity mention identifier and cluster outcome")
def step_valid_identifier_and_cluster(ctx):
    ctx["identifier"] = make_identifier()
    ctx["cluster"] = make_cluster()
    ctx["candidates"] = []
    ctx["updated_at"] = datetime.now(UTC)


@given("an existing decision for a triad")
def step_existing_decision(ctx, mock_repo):
    ctx["identifier"] = make_identifier()
    ctx["now"] = datetime.now(UTC)
    ctx["cluster"] = make_cluster("c1")
    decision = make_decision(ctx["now"], cluster_id="c1")
    mock_repo.upsert_decision = AsyncMock(return_value=decision)


@given(parsers.parse('an existing decision with updated_at "{stored_ts}"'))
def step_existing_decision_with_timestamp(ctx, mock_repo, stored_ts):
    ctx["identifier"] = make_identifier()
    ctx["stored_ts"] = datetime.fromisoformat(stored_ts.replace("Z", "+00:00"))


@given("a valid entity mention identifier and 10 candidates")
def step_identifier_with_many_candidates(ctx):
    ctx["identifier"] = make_identifier()
    ctx["cluster"] = make_cluster()
    ctx["candidates"] = [make_cluster(f"c{i}") for i in range(10)]
    ctx["updated_at"] = datetime.now(UTC)


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("I store the decision")
def step_store_decision(ctx, service, mock_repo):
    now = ctx["updated_at"]
    # First insert: no existing decision for this triad (R1: updated_at stays None)
    mock_repo.find_by_triad = AsyncMock(return_value=None)
    inserted = Decision(
        id="hash123",
        about_entity_mention=ctx["identifier"],
        current_placement=ctx["cluster"],
        candidates=[],
        created_at=now,
        updated_at=None,  # On first insert, updated_at is not set
    )
    mock_repo.upsert_decision = AsyncMock(return_value=inserted)
    try:
        ctx["result"] = asyncio.run(
            store_decision(
                ctx["identifier"], ctx["cluster"], ctx["candidates"], now, service=service
            )
        )
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when("I store the same triad with a newer updated_at")
def step_store_newer_timestamp(ctx, service, mock_repo):
    newer_ts = ctx["now"] + timedelta(seconds=5)
    newer_decision = make_decision(newer_ts, cluster_id="c2")
    # Existing decision has cluster_id="c1"; incoming has "c2" → different placement → upsert
    existing = make_decision(ctx["now"], cluster_id="c1")
    mock_repo.find_by_triad = AsyncMock(return_value=existing)
    mock_repo.upsert_decision = AsyncMock(return_value=newer_decision)
    try:
        ctx["result"] = asyncio.run(
            store_decision(
                ctx["identifier"], make_cluster("c2"), [], newer_ts, service=service
            )
        )
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when(parsers.parse('I attempt to store the same triad with updated_at "{attempt_ts}"'))
def step_attempt_store_stale(ctx, service, mock_repo, attempt_ts):
    attempt = datetime.fromisoformat(attempt_ts.replace("Z", "+00:00"))
    mock_repo.upsert_decision = AsyncMock(
        side_effect=StaleOutcomeError(
            "s1", "r1", "Person",
            stored_at=str(ctx["stored_ts"]),
            attempted_at=str(attempt),
        )
    )
    try:
        asyncio.run(
            store_decision(ctx["identifier"], make_cluster(), [], attempt, service=service)
        )
        ctx["raised_exception"] = None
    except StaleOutcomeError as exc:
        ctx["raised_exception"] = exc


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the stored record matches the input")
def step_record_matches_input(ctx):
    assert ctx["raised_exception"] is None, ctx["raised_exception"]
    assert isinstance(ctx["result"], Decision)
    assert ctx["result"].about_entity_mention == ctx["identifier"]
    assert ctx["result"].current_placement == ctx["cluster"]


@then("the record reflects the updated cluster")
def step_record_reflects_updated(ctx):
    assert ctx["raised_exception"] is None, ctx["raised_exception"]
    assert isinstance(ctx["result"], Decision)
    assert ctx["result"].current_placement.cluster_id == "c2"


@then("a StaleOutcomeError is raised")
def step_stale_error_raised(ctx):
    assert isinstance(ctx["raised_exception"], StaleOutcomeError)


@then("the stored record has at most 5 candidates")
def step_candidates_capped(ctx, mock_repo):
    assert ctx["raised_exception"] is None, ctx["raised_exception"]
    call_kwargs = mock_repo.upsert_decision.call_args.kwargs
    assert len(call_kwargs["candidates"]) <= config.DECISION_STORE_MAX_CANDIDATES
