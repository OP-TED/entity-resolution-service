"""
Step definitions for: refresh_bulk_delta_semantics.feature

Feature: Refresh-Bulk Cold-Start and Idempotent ERE Re-confirmation Semantics
  Covers three behaviours:
    F-01: Cold-start — all placements stable → empty delta.
    F-02: Cold-start — some corrected placements → only changed ones returned.
    F-03: Ongoing consumer — ERE re-confirms same placement → NOT in next delta.

  These steps call BulkRefreshCoordinatorService with mocked dependencies.
  The Decision Store mock is wired so that cold-start returns only decisions
  with non-null updated_at (the service-layer contract from R3).
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from pytest_bdd import given, parsers, scenarios, then, when

from ers.commons.domain.data_transfer_objects import CursorPage
from ers.request_registry.domain.records import LookupRequestRecord
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_coordinator.services.bulk_refresh_coordinator_service import (
    BulkRefreshCoordinatorService,
)
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE_FILE = str(
    Path(__file__).parent.parent.parent
    / "feature"
    / "resolution_coordinator"
    / "refresh_bulk_delta_semantics.feature"
)

scenarios(FEATURE_FILE)


# ---------------------------------------------------------------------------
# Shared context fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Mutable scenario context shared across step functions."""
    registry_svc = create_autospec(RequestRegistryService, instance=True)
    decision_svc = create_autospec(DecisionStoreService, instance=True)
    service = BulkRefreshCoordinatorService(
        registry_service=registry_svc,
        decision_store_service=decision_svc,
    )
    return {
        "registry_svc": registry_svc,
        "decision_svc": decision_svc,
        "service": service,
        "source_id": None,
        "result": None,
        "raised_exception": None,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_decision(source_id: str, idx: int, updated_at: datetime | None = None) -> Decision:
    """Build a minimal Decision with deterministic identifiers."""
    created = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
    ident = EntityMentionIdentifier(
        source_id=source_id, request_id=f"req-{idx}", entity_type="Organization"
    )
    cluster = ClusterReference(cluster_id=f"cl-{idx}", confidence_score=0.9, similarity_score=0.85)
    return Decision(
        id=f"hash-{idx}",
        about_entity_mention=ident,
        current_placement=cluster,
        candidates=[cluster],
        created_at=created,
        updated_at=updated_at,
    )


# ---------------------------------------------------------------------------
# Background steps
# ---------------------------------------------------------------------------


@given("the Resolution Coordinator is available with all dependency services")
def coordinator_available(ctx):
    """Service is already built in the ctx fixture."""


@given("the Request Registry tracks lookup state per source")
def registry_tracks_lookup_state(ctx):
    """Install baseline mocks — source exists, no prior snapshot."""
    ctx["registry_svc"].source_has_requests = AsyncMock(return_value=True)
    ctx["registry_svc"].get_lookup_state = AsyncMock(return_value=None)
    ctx["registry_svc"].advance_snapshot = AsyncMock(return_value=None)


@given("the Decision Store persists placement decisions per entity mention triad")
def decision_store_persists(ctx):
    """Decision Store mock is already wired via ctx fixture; no extra setup needed."""


# ---------------------------------------------------------------------------
# F-01: Cold-start — no placement has ever changed
# ---------------------------------------------------------------------------


@given(parsers.parse('source "{source_id}" has never performed a bulk lookup'))
def source_no_prior_lookup(ctx, source_id):
    """Source exists but has no LookupRequestRecord (cold start)."""
    ctx["source_id"] = source_id
    ctx["registry_svc"].source_has_requests = AsyncMock(return_value=True)
    ctx["registry_svc"].get_lookup_state = AsyncMock(return_value=None)
    ctx["registry_svc"].advance_snapshot = AsyncMock(return_value=None)


@given(parsers.parse('source "{source_id}" has {mention_count:d} registered entity mentions'))
def source_has_mentions(ctx, source_id, mention_count):
    """Record the mention count for later use by downstream steps."""
    ctx["mention_count"] = mention_count


@given(
    "ERE has only ever confirmed the same placement for each of those mentions"
)
def ere_only_confirmed_same_placement(ctx):
    """All decisions have updated_at=None (no placement ever changed).

    On cold start the service returns only decisions with non-null updated_at,
    so the mock returns an empty page.
    """
    ctx["decision_svc"].query_decisions_delta = AsyncMock(
        return_value=CursorPage(results=[], next_cursor=None)
    )


@given(
    parsers.parse(
        'therefore all decisions for source "{source_id}" have an unset updated_at'
    )
)
def all_decisions_have_unset_updated_at(ctx, source_id):
    """Restate the no-op condition for clarity — mock already set above."""


# ---------------------------------------------------------------------------
# F-02: Cold-start — some corrected placements
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        'source "{source_id}" has {total_mentions:d} registered entity mentions'
    )
)
def source_has_total_mentions(ctx, source_id, total_mentions):
    """Record total mention count."""
    ctx["total_mentions"] = total_mentions


@given(
    parsers.parse(
        "{stable_count:d} of those have always kept the same placement"
        " and therefore have an unset updated_at"
    )
)
def stable_mentions_with_unset_updated_at(ctx, stable_count):
    """Record stable count for assertion."""
    ctx["stable_count"] = stable_count


@given(
    parsers.parse(
        "{changed_count:d} of those had their placement corrected at least once"
        " and therefore have a non-null updated_at"
    )
)
def changed_mentions_with_non_null_updated_at(ctx, changed_count):
    """Wire the mock: cold-start returns only the changed (non-null updated_at) decisions."""
    ctx["changed_count"] = changed_count
    source_id = ctx.get("source_id", "UNKNOWN")
    changed_ts = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
    changed_decisions = [
        _make_decision(source_id, i, updated_at=changed_ts) for i in range(changed_count)
    ]
    ctx["decision_svc"].query_decisions_delta = AsyncMock(
        return_value=CursorPage(results=changed_decisions, next_cursor=None)
    )


# ---------------------------------------------------------------------------
# F-03: Ongoing consumer — ERE re-confirmation
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        'source "{source_id}" last performed a bulk lookup at "{snapshot_ts}"'
    )
)
def source_last_bulk_lookup(ctx, source_id, snapshot_ts):
    """Source has a prior snapshot — not a cold start."""
    ctx["source_id"] = source_id
    ts = datetime.fromisoformat(snapshot_ts.replace("Z", "+00:00"))
    record = LookupRequestRecord(source_id=source_id, last_snapshot=ts, updated_at=ts)
    ctx["registry_svc"].source_has_requests = AsyncMock(return_value=True)
    ctx["registry_svc"].get_lookup_state = AsyncMock(return_value=record)
    ctx["registry_svc"].advance_snapshot = AsyncMock(return_value=None)


@given(
    parsers.parse(
        'the Decision Store contains a decision for mention "{mention_id}"'
        ' of source "{source_id}"'
        ' whose placement was last changed at "{changed_ts}"'
    )
)
def decision_store_has_mention_changed_at(ctx, mention_id, source_id, changed_ts):
    """Record scenario parameters — mock is configured in the re-confirmation step."""
    ctx["mention_id"] = mention_id


@given(
    "that decision was therefore included in a prior bulk lookup response"
)
def decision_was_in_prior_response(ctx):
    """The decision was returned in the previous refresh-bulk call; nothing to stub here."""


@when(
    parsers.parse(
        "ERE re-confirms the same placement for mention"
        ' "{mention_id}" with a later outcome timestamp'
    )
)
def ere_reconfirms_same_placement(ctx, mention_id):
    """ERE re-confirmation step — no decision_svc write occurs at this layer."""


@when("the Decision Store records the re-confirmation without changing updated_at")
def decision_store_records_reconfirmation(ctx):
    """The Decision Store short-circuits on same placement; updated_at stays the same.

    The subsequent bulk lookup query uses updated_since = last_snapshot (2026-05-01T09:00:00Z).
    The re-confirmed decision has updated_at = 2026-04-30T08:00:00Z, which is before
    the snapshot, so the mock returns an empty page.
    """
    ctx["decision_svc"].query_decisions_delta = AsyncMock(
        return_value=CursorPage(results=[], next_cursor=None)
    )


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(parsers.parse('a bulk lookup is requested for source "{source_id}"'))
def request_bulk_lookup(ctx, source_id):
    """Invoke refresh_bulk and capture the result or exception."""
    try:
        ctx["result"] = asyncio.run(ctx["service"].refresh_bulk(source_id))
        ctx["raised_exception"] = None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when("a subsequent bulk lookup is requested for source \"SOURCE_F03\"")
def subsequent_bulk_lookup_f03(ctx):
    """Trigger the next refresh-bulk after the re-confirmation."""
    try:
        ctx["result"] = asyncio.run(ctx["service"].refresh_bulk("SOURCE_F03"))
        ctx["raised_exception"] = None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ctx["result"] = None
        ctx["raised_exception"] = exc


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the response contains no cluster assignment deltas")
def response_is_empty(ctx):
    """Assert the result page has no decisions."""
    assert ctx["raised_exception"] is None, f"Unexpected exception: {ctx['raised_exception']}"
    assert ctx["result"].results == [], (
        f"Expected empty result, got {len(ctx['result'].results)} decisions"
    )


@then("has_more is false")
def has_more_is_false(ctx):
    """Assert no next page cursor is present."""
    assert ctx["result"].next_cursor is None, (
        f"Expected next_cursor=None, got {ctx['result'].next_cursor!r}"
    )


@then(
    parsers.parse(
        'the last notification date for source "{source_id}" is created and advanced to now'
    )
)
def last_notification_date_created_and_advanced(ctx, source_id):
    """Assert that advance_snapshot was called exactly once (creating/updating the record)."""
    ctx["registry_svc"].advance_snapshot.assert_awaited_once()


@then(
    parsers.parse(
        'the last notification date for source "{source_id}" is advanced to now'
    )
)
def last_notification_date_advanced(ctx, source_id):
    """Assert that advance_snapshot was called exactly once."""
    ctx["registry_svc"].advance_snapshot.assert_awaited_once()


@then(parsers.parse("the response contains exactly {changed_count:d} cluster assignment deltas"))
def response_contains_n_deltas(ctx, changed_count):
    """Assert the response has exactly changed_count decisions."""
    assert ctx["raised_exception"] is None, f"Unexpected exception: {ctx['raised_exception']}"
    assert len(ctx["result"].results) == changed_count, (
        f"Expected {changed_count} decisions, got {len(ctx['result'].results)}"
    )


@then(
    parsers.parse(
        "the {stable_count:d} mentions with an unset updated_at are not present in the response"
    )
)
def stable_mentions_not_in_response(ctx, stable_count):
    """Stable decisions (updated_at=None) must not appear in results."""
    for decision in ctx["result"].results:
        assert decision.updated_at is not None, (
            "Found a decision with updated_at=None in the response — "
            "stable decisions must be filtered out"
        )


@then(parsers.parse('mention "{mention_id}" is not present in the response'))
def mention_not_in_response(ctx, mention_id):
    """Assert the specific mention is absent from the result."""
    assert ctx["raised_exception"] is None, f"Unexpected exception: {ctx['raised_exception']}"
    result_request_ids = [
        d.about_entity_mention.request_id for d in ctx["result"].results
    ]
    assert mention_id not in result_request_ids, (
        f"Mention {mention_id!r} unexpectedly found in response"
    )
