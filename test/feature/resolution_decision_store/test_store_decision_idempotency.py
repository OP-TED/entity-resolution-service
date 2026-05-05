"""
Step definitions for: store_decision_idempotency.feature

Feature: Idempotent Decision Storage with Placement-Change Detection
  Covers five scenario groups:
    1. First insert: created_at set, updated_at left unset.
    2. ERE re-confirmation (same placement): no-op, no timestamp bump.
    3. Genuine placement change: updated_at set, created_at preserved.
    4. Stale-outcome rejection: write with old timestamp raises StaleOutcomeError.
    5. Fresh-vs-created_at: stale check uses created_at when updated_at is unset.

  Steps call DecisionStoreService directly through a mocked MongoDecisionRepository.

Note on step patterns:
  parsers.parse("{x}") is greedy and can swallow quoted content across boundaries.
  For steps whose text differs only by middle tokens, parsers.re with ([^"]+) is used
  to enforce that captures do not span the literal quote delimiters.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from pytest_bdd import given, parsers, scenarios, then, when

from ers.resolution_decision_store.domain.errors import StaleOutcomeError
from ers.resolution_decision_store.services.decision_store_service import store_decision

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE_FILE = str(Path(__file__).parent / "store_decision_idempotency.feature")

scenarios(FEATURE_FILE)


# ---------------------------------------------------------------------------
# Constants / Helpers
# ---------------------------------------------------------------------------

_SENTINEL_NONE = "unset"  # token used in Examples tables to represent None


def _parse_ts(raw: str) -> datetime | None:
    """Parse ISO 8601 timestamp, returning None for the 'unset' sentinel."""
    if raw.strip() == _SENTINEL_NONE:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _make_identifier(triad: str) -> EntityMentionIdentifier:
    return EntityMentionIdentifier(
        source_id="test-source",
        request_id=triad,
        entity_type="Organization",
    )


def _make_cluster(cluster_id: str) -> ClusterReference:
    return ClusterReference(
        cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85
    )


def _make_decision(
    triad: str,
    placement: str,
    created_at: datetime,
    updated_at: datetime | None,
) -> Decision:
    return Decision(
        id=f"hash-{triad}",
        about_entity_mention=_make_identifier(triad),
        current_placement=_make_cluster(placement),
        candidates=[],
        created_at=created_at,
        updated_at=updated_at,
    )


# ---------------------------------------------------------------------------
# Background step
# ---------------------------------------------------------------------------


@given("the Decision Store is available")
def decision_store_available(ctx, mock_repo):  # pylint: disable=unused-argument
    """Service and mock_repo are already wired by the conftest fixtures."""


# ---------------------------------------------------------------------------
# Scenario 1 — First insert
# ---------------------------------------------------------------------------


@given(parsers.re(r'no decision exists for entity mention triad "(?P<triad>[^"]+)"'))
def no_decision_for_triad(ctx, mock_repo, triad):
    """Configure find_by_triad to return None (no existing record)."""
    ctx["triad"] = triad
    mock_repo.find_by_triad = AsyncMock(return_value=None)


@when(
    parsers.re(
        r'a decision is stored for triad "(?P<triad>[^"]+)"'
        r' with placement "(?P<placement>[^"]+)"'
        r' and outcome timestamp "(?P<outcome_ts>[^"]+)"'
    )
)
def store_for_new_triad(ctx, mock_repo, service, triad, placement, outcome_ts):
    """Store a brand-new decision; upsert_decision returns it with updated_at=None."""
    ts = _parse_ts(outcome_ts)
    inserted = _make_decision(triad, placement, created_at=ts, updated_at=None)
    mock_repo.upsert_decision = AsyncMock(return_value=inserted)
    ctx["placement"] = placement
    ctx["outcome_ts"] = ts
    try:
        ctx["result"] = asyncio.run(
            store_decision(
                _make_identifier(triad),
                _make_cluster(placement),
                [],
                ts,
                service=service,
            )
        )
        ctx["raised_exception"] = None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ctx["result"] = None
        ctx["raised_exception"] = exc


@then(
    parsers.re(
        r'a decision exists for triad "(?P<triad>[^"]+)"'
        r' with placement "(?P<placement>[^"]+)"'
    )
)
def decision_exists_with_placement(ctx, triad, placement):
    assert ctx["raised_exception"] is None, f"Unexpected exception: {ctx['raised_exception']}"
    assert ctx["result"] is not None
    assert ctx["result"].current_placement.cluster_id == placement


@then(parsers.re(r'the stored created_at is "(?P<expected_ts>[^"]+)"'))
def stored_created_at_matches(ctx, expected_ts):
    expected = _parse_ts(expected_ts)
    assert ctx["result"].created_at == expected, (
        f"created_at mismatch: expected {expected}, got {ctx['result'].created_at}"
    )


@then("the stored updated_at is unset")
def stored_updated_at_is_unset(ctx):
    assert ctx["result"].updated_at is None, (
        f"Expected updated_at=None, got {ctx['result'].updated_at!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 2 — ERE re-confirmation (same placement → no-op)
# ---------------------------------------------------------------------------

# Matches: a decision exists for triad "X" with placement "Y" created_at "Z" and updated_at unset
_RE_GIVEN_WITH_CREATED_AT_UNSET = (
    r'a decision exists for triad "(?P<triad>[^"]+)"'
    r' with placement "(?P<placement>[^"]+)"'
    r' created_at "(?P<created_at>[^"]+)"'
    r" and updated_at unset"
)


@given(parsers.re(_RE_GIVEN_WITH_CREATED_AT_UNSET))
def existing_decision_unset_updated_at(ctx, mock_repo, triad, placement, created_at):
    """Wire find_by_triad to return an existing decision with updated_at=None."""
    ts = _parse_ts(created_at)
    existing = _make_decision(triad, placement, created_at=ts, updated_at=None)
    mock_repo.find_by_triad = AsyncMock(return_value=existing)
    ctx["triad"] = triad
    ctx["existing_decision"] = existing
    ctx["existing_placement"] = placement
    ctx["existing_created_at"] = ts


@when(
    parsers.re(
        r'a decision is stored for triad "(?P<triad>[^"]+)"'
        r' with the same placement "(?P<placement>[^"]+)"'
        r' and a later outcome timestamp "(?P<later_ts>[^"]+)"'
    )
)
def store_same_placement(ctx, mock_repo, service, triad, placement, later_ts):
    """Re-storing the same placement must be a no-op (service short-circuits before upsert)."""
    ts = _parse_ts(later_ts)
    # upsert_decision must NOT be called — configure it to fail if it is
    mock_repo.upsert_decision = AsyncMock(
        side_effect=AssertionError("upsert_decision called on a no-op re-confirmation")
    )
    try:
        ctx["result"] = asyncio.run(
            store_decision(
                _make_identifier(triad),
                _make_cluster(placement),
                [],
                ts,
                service=service,
            )
        )
        ctx["raised_exception"] = None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ctx["result"] = None
        ctx["raised_exception"] = exc


@then("the stored decision is unchanged")
def stored_decision_is_unchanged(ctx):
    """Asserts the stored decision was not modified.

    Handles two cases:
    - No-op re-confirmation (Scenario 2): returned result is the existing Decision.
    - Stale rejection (Scenario 4): a StaleOutcomeError was raised, no update occurred.
    """
    exc = ctx.get("raised_exception")
    if isinstance(exc, StaleOutcomeError):
        # Unchanged is guaranteed because upsert_decision raised before any write.
        return
    assert exc is None, f"Unexpected exception: {exc}"
    assert ctx["result"] is not None
    assert ctx["result"] is ctx["existing_decision"], (
        "Expected the existing Decision to be returned unchanged"
    )


@then(parsers.re(r'the stored created_at is still "(?P<expected_ts>[^"]+)"'))
def stored_created_at_still_matches(ctx, expected_ts):
    expected = _parse_ts(expected_ts)
    assert ctx["result"].created_at == expected, (
        f"created_at changed unexpectedly: expected {expected}, got {ctx['result'].created_at}"
    )


@then("the stored updated_at is still unset")
def stored_updated_at_still_unset(ctx):
    assert ctx["result"].updated_at is None, (
        f"updated_at was bumped unexpectedly: got {ctx['result'].updated_at!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 3 — Genuine placement change
# ---------------------------------------------------------------------------

# Matches: a decision exists for triad "X" with placement "Y" created_at "Z" and updated_at "W"
# The updated_at token here is a quoted timestamp (possibly "unset"), not a bare word.
_RE_GIVEN_WITH_PRIOR_UPDATED_AT = (
    r'a decision exists for triad "(?P<triad>[^"]+)"'
    r' with placement "(?P<old_placement>[^"]+)"'
    r' created_at "(?P<created_at>[^"]+)"'
    r' and updated_at "(?P<prior_updated_at>[^"]+)"'
)


@given(parsers.re(_RE_GIVEN_WITH_PRIOR_UPDATED_AT))
def existing_decision_with_prior_updated_at(
    ctx, mock_repo, triad, old_placement, created_at, prior_updated_at
):
    """Wire find_by_triad with an existing decision that may already have an updated_at."""
    created = _parse_ts(created_at)
    updated = _parse_ts(prior_updated_at)
    existing = _make_decision(triad, old_placement, created_at=created, updated_at=updated)
    mock_repo.find_by_triad = AsyncMock(return_value=existing)
    ctx["triad"] = triad
    ctx["existing_decision"] = existing
    ctx["existing_created_at"] = created


@when(
    parsers.re(
        r'a decision is stored for triad "(?P<triad>[^"]+)"'
        r' with a different placement "(?P<new_placement>[^"]+)"'
        r' and outcome timestamp "(?P<new_ts>[^"]+)"'
    )
)
def store_different_placement(ctx, mock_repo, service, triad, new_placement, new_ts):
    """Storing a different placement must call upsert_decision and bump updated_at."""
    ts = _parse_ts(new_ts)
    existing = ctx["existing_decision"]
    updated = _make_decision(
        triad, new_placement, created_at=existing.created_at, updated_at=ts
    )
    mock_repo.upsert_decision = AsyncMock(return_value=updated)
    ctx["expected_new_placement"] = new_placement
    ctx["expected_updated_at"] = ts
    try:
        ctx["result"] = asyncio.run(
            store_decision(
                _make_identifier(triad),
                _make_cluster(new_placement),
                [],
                ts,
                service=service,
            )
        )
        ctx["raised_exception"] = None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ctx["result"] = None
        ctx["raised_exception"] = exc


@then(parsers.re(r'the stored decision has placement "(?P<new_placement>[^"]+)"'))
def stored_decision_has_new_placement(ctx, new_placement):
    assert ctx["raised_exception"] is None, f"Unexpected exception: {ctx['raised_exception']}"
    assert ctx["result"].current_placement.cluster_id == new_placement, (
        f"Expected placement {new_placement!r}, got {ctx['result'].current_placement.cluster_id!r}"
    )


@then(parsers.re(r'the stored updated_at is "(?P<expected_ts>[^"]+)"'))
def stored_updated_at_matches(ctx, expected_ts):
    expected = _parse_ts(expected_ts)
    assert ctx["result"].updated_at == expected, (
        f"updated_at mismatch: expected {expected}, got {ctx['result'].updated_at!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 4 — Stale-outcome rejection
# ---------------------------------------------------------------------------

# Matches: a decision exists for triad "X" with placement "Y" and updated_at "Z"
# (no "created_at" token — distinct from Scenario 3 Given)
_RE_GIVEN_WITH_UPDATED_AT_ONLY = (
    r'a decision exists for triad "(?P<triad>[^"]+)"'
    r' with placement "(?P<placement>[^"]+)"'
    r' and updated_at "(?P<stored_ts>[^"]+)"'
)


@given(parsers.re(_RE_GIVEN_WITH_UPDATED_AT_ONLY))
def existing_decision_with_updated_at(ctx, mock_repo, triad, placement, stored_ts):
    """Wire find_by_triad with a decision that has a concrete non-null updated_at."""
    ts = _parse_ts(stored_ts)
    existing = _make_decision(
        triad, placement, created_at=datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC), updated_at=ts
    )
    mock_repo.find_by_triad = AsyncMock(return_value=existing)
    ctx["triad"] = triad
    ctx["existing_decision"] = existing
    ctx["stored_ts"] = ts


@when(
    parsers.re(
        r'a decision is stored for triad "(?P<triad>[^"]+)"'
        r' with a different placement and outcome timestamp'
        r' "(?P<attempt_ts>[^"]+)"'
    )
)
def store_stale_outcome(ctx, mock_repo, service, triad, attempt_ts):
    """Attempt a write with a stale timestamp; upsert_decision raises StaleOutcomeError."""
    ts = _parse_ts(attempt_ts)
    mock_repo.upsert_decision = AsyncMock(
        side_effect=StaleOutcomeError(
            "test-source",
            triad,
            "Organization",
            stored_at=str(ctx["stored_ts"]),
            attempted_at=str(ts),
        )
    )
    ctx["result"] = None
    try:
        asyncio.run(
            store_decision(
                _make_identifier(triad),
                _make_cluster("cluster-Z"),  # a different placement
                [],
                ts,
                service=service,
            )
        )
        ctx["raised_exception"] = None
    except StaleOutcomeError as exc:
        ctx["raised_exception"] = exc
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ctx["raised_exception"] = exc


@then("a StaleOutcomeError is raised")
def stale_outcome_error_raised(ctx):
    assert isinstance(ctx["raised_exception"], StaleOutcomeError), (
        f"Expected StaleOutcomeError, got {type(ctx.get('raised_exception')).__name__}"
    )



# ---------------------------------------------------------------------------
# Scenario 5 — Fresh-vs-created_at comparison
# ---------------------------------------------------------------------------


@when(
    parsers.re(
        r'a decision is stored for triad "(?P<triad>[^"]+)"'
        r' with a different placement "cluster-B"'
        r' and outcome timestamp "(?P<attempt_ts>[^"]+)"'
    )
)
def store_against_never_moved_decision(ctx, mock_repo, service, triad, attempt_ts):
    """Attempt to store a different placement; staleness checked against created_at."""
    ts = _parse_ts(attempt_ts)
    existing = ctx["existing_decision"]
    created_at = existing.created_at

    if ts is None or ts <= created_at:
        # Stale: timestamp is not strictly greater than created_at
        mock_repo.upsert_decision = AsyncMock(
            side_effect=StaleOutcomeError(
                "test-source",
                triad,
                "Organization",
                stored_at=str(created_at),
                attempted_at=str(ts),
            )
        )
    else:
        # Fresh: write succeeds
        updated_decision = _make_decision(
            triad, "cluster-B", created_at=created_at, updated_at=ts
        )
        mock_repo.upsert_decision = AsyncMock(return_value=updated_decision)

    ctx["result"] = None
    ctx["raised_exception"] = None
    try:
        ctx["result"] = asyncio.run(
            store_decision(
                _make_identifier(triad),
                _make_cluster("cluster-B"),
                [],
                ts,
                service=service,
            )
        )
        ctx["outcome"] = "accepted"
    except StaleOutcomeError:
        ctx["outcome"] = "rejected"
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ctx["raised_exception"] = exc
        ctx["outcome"] = "error"


@then(parsers.re(r'the outcome is "(?P<expected_outcome>[^"]+)"'))
def outcome_matches(ctx, expected_outcome):
    assert ctx.get("raised_exception") is None, (
        f"Unexpected non-StaleOutcomeError exception: {ctx.get('raised_exception')}"
    )
    assert ctx.get("outcome") == expected_outcome, (
        f"Expected outcome {expected_outcome!r}, got {ctx.get('outcome')!r}"
    )
