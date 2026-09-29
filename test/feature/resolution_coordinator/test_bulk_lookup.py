"""
Step definitions for: bulk_lookup.feature

Feature: Bulk Cluster Assignment Lookup (refreshBulk — Spine C)
  Covers three behaviours:
    1. Return changed decisions since last lookup, advance last notification date.
    2. Reject lookups that cannot be fulfilled (unknown source, Decision Store down).
    3. Bulk lookup is strictly read-only.

  These steps call BulkRefreshCoordinatorService with mocked dependencies.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from pytest_bdd import given, parsers, scenario, then, when

from ers.commons.domain.data_transfer_objects import CursorPage
from ers.request_registry.domain.records import LookupRequestRecord
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_coordinator.domain.exceptions import SourceNotFoundError
from ers.resolution_coordinator.services.bulk_refresh_coordinator_service import (
    BulkRefreshCoordinatorService,
)
from ers.resolution_decision_store.domain.errors import RepositoryConnectionError
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE_FILE = str(
    Path(__file__).parent.parent.parent
    / "feature"
    / "resolution_coordinator"
    / "bulk_lookup.feature"
)


@scenario(
    FEATURE_FILE,
    "Return decisions changed since the last lookup and advance the last notification date",
)
def test_return_changed_decisions():
    pass


@scenario(FEATURE_FILE, "Reject a lookup that cannot be fulfilled")
def test_reject_unfulfillable_lookup():
    pass


@scenario(FEATURE_FILE, "Bulk lookup is strictly read-only")
def test_read_only():
    pass


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
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
        "result": None,
        "raised_exception": None,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_decision(source_id: str, idx: int) -> Decision:
    now = datetime.now(UTC)
    ident = EntityMentionIdentifier(
        source_id=source_id, request_id=f"req-{idx}", entity_type="Organization"
    )
    cluster = ClusterReference(cluster_id=f"cl-{idx}", confidence_score=0.9, similarity_score=0.85)
    return Decision(
        id=f"hash-{idx}",
        about_entity_mention=ident,
        current_placement=cluster,
        candidates=[cluster],
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("the Resolution Coordinator is available with all dependency services")
def coordinator_available(ctx):
    # Service already built in ctx fixture.
    pass


@given("the Request Registry tracks lookup state per source")
def registry_tracks_lookup_state(ctx):
    # Defaults: source exists, no prior snapshot.
    ctx["registry_svc"].source_has_requests = AsyncMock(return_value=True)
    ctx["registry_svc"].get_lookup_state = AsyncMock(return_value=None)
    ctx["registry_svc"].advance_snapshot = AsyncMock(return_value=None)


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(parsers.parse('source "{source_id}" "{prior_lookup_state}"'))
def source_with_prior_state(ctx, source_id, prior_lookup_state):
    ctx["source_id"] = source_id

    if "Decision Store is unavailable" in prior_lookup_state:
        # Source exists but Decision Store is down after snapshot lookup.
        ts = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
        record = LookupRequestRecord(source_id=source_id, last_snapshot=ts, updated_at=ts)
        ctx["registry_svc"].source_has_requests = AsyncMock(return_value=True)
        ctx["registry_svc"].get_lookup_state = AsyncMock(return_value=record)
        ctx["registry_svc"].advance_snapshot = AsyncMock(return_value=None)
        ctx["decision_svc"].query_decisions_delta = AsyncMock(
            side_effect=RepositoryConnectionError("MongoDB down")
        )

    elif "last performed a bulk lookup at" in prior_lookup_state:
        ts_str = prior_lookup_state.replace("last performed a bulk lookup at", "").strip()
        ts = datetime.fromisoformat(ts_str).replace(tzinfo=UTC)
        record = LookupRequestRecord(source_id=source_id, last_snapshot=ts, updated_at=ts)
        ctx["registry_svc"].source_has_requests = AsyncMock(return_value=True)
        ctx["registry_svc"].get_lookup_state = AsyncMock(return_value=record)
        ctx["registry_svc"].advance_snapshot = AsyncMock(return_value=None)

    elif "has never performed a bulk lookup" in prior_lookup_state:
        ctx["registry_svc"].source_has_requests = AsyncMock(return_value=True)
        ctx["registry_svc"].get_lookup_state = AsyncMock(return_value=None)
        ctx["registry_svc"].advance_snapshot = AsyncMock(return_value=None)

    elif "has no resolution requests" in prior_lookup_state:
        ctx["registry_svc"].source_has_requests = AsyncMock(return_value=False)

    # "last performed a bulk lookup but the Decision Store is unavailable" handled above.


@given(
    parsers.parse(
        'the Decision Store contains {total:d} decisions for source "{source_id}" '
        "with {changed:d} updated since the last lookup"
    )
)
def decision_store_has_decisions(ctx, total, source_id, changed):
    decisions = [_make_decision(source_id, i) for i in range(changed)]
    ctx["decision_svc"].query_decisions_delta = AsyncMock(
        return_value=CursorPage(results=decisions, next_cursor=None)
    )


@given(parsers.parse('source "{source_id}" last performed a bulk lookup at {timestamp}'))
def source_last_lookup(ctx, source_id, timestamp):
    ts = datetime.fromisoformat(timestamp).replace(tzinfo=UTC)
    record = LookupRequestRecord(source_id=source_id, last_snapshot=ts, updated_at=ts)
    ctx["source_id"] = source_id
    ctx["registry_svc"].source_has_requests = AsyncMock(return_value=True)
    ctx["registry_svc"].get_lookup_state = AsyncMock(return_value=record)
    ctx["registry_svc"].advance_snapshot = AsyncMock(return_value=None)
    ctx["decision_svc"].query_decisions_delta = AsyncMock(
        return_value=CursorPage(results=[], next_cursor=None)
    )


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(parsers.parse('a bulk lookup is requested for source "{source_id}"'))
def request_bulk_lookup(ctx, source_id):
    try:
        ctx["result"] = asyncio.run(ctx["service"].refresh_bulk(source_id))
        ctx["raised_exception"] = None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ctx["result"] = None
        ctx["raised_exception"] = exc


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.parse("{count:d} cluster assignments are returned"))
def n_assignments_returned(ctx, count):
    assert ctx["raised_exception"] is None, f"Unexpected exception: {ctx['raised_exception']}"
    assert len(ctx["result"].results) == count


@then("the last notification date is advanced")
def notification_date_advanced(ctx):
    ctx["registry_svc"].advance_snapshot.assert_awaited_once()


@then("a last notification date is created")
def notification_date_created(ctx):
    ctx["registry_svc"].advance_snapshot.assert_awaited_once()


@then(parsers.parse('a "{error_type}" error is returned'))
def typed_error_returned(ctx, error_type):
    exc = ctx["raised_exception"]
    assert exc is not None, "Expected an exception but none was raised"
    if error_type == "not_found":
        assert isinstance(exc, SourceNotFoundError), (
            f"Expected SourceNotFoundError, got {type(exc).__name__}"
        )
    elif error_type == "service":
        assert isinstance(exc, RepositoryConnectionError), (
            f"Expected RepositoryConnectionError, got {type(exc).__name__}"
        )
    else:
        raise ValueError(f"Unknown error_type: {error_type!r}")


@then("the last notification date is not modified")
def notification_date_not_modified(ctx):
    ctx["registry_svc"].advance_snapshot.assert_not_awaited()


@then("no resolution requests are published to the ERE")
def no_ere_publish(ctx):
    # BulkRefreshCoordinatorService has no publish service — structurally enforced.
    pass


@then("no decisions are written to the Decision Store")
def no_decision_writes(ctx):
    ctx["decision_svc"].store_decision.assert_not_called()


@then("no requests are registered in the Request Registry")
def no_registration(ctx):
    ctx["registry_svc"].register_resolution_request.assert_not_called()
