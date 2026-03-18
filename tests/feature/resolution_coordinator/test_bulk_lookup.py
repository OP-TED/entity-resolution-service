"""
Step definitions for: bulk_lookup.feature

Feature: Bulk Cluster Assignment Lookup (refreshBulk — Spine C)
  Covers three behaviours:
    1. Return changed decisions since last lookup, advance last notification date.
    2. Reject lookups that cannot be fulfilled (unknown source, Decision Store down).
    3. Bulk lookup is strictly read-only.

  These steps call the ResolutionCoordinatorService with mocked dependencies.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenario, then, when

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
    """Shared mutable context for passing state between step functions."""
    return {}


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("the Resolution Coordinator is available with all dependency services")
def coordinator_available(ctx):
    """
    TODO: Same setup as other coordinator step files.
    """
    ctx["registry_service"] = MagicMock()
    ctx["decision_store_service"] = MagicMock()
    ctx["publish_service"] = MagicMock()
    ctx["service"] = None  # TODO: build real ResolutionCoordinatorService


@given("the Request Registry tracks lookup state per source")
def registry_tracks_lookup_state(ctx):
    """
    TODO: Configure registry mock to support get_lookup_state / advance_lookup.
    """
    ctx["registry_service"].get_lookup_state = AsyncMock(return_value=None)
    ctx["registry_service"].advance_lookup = AsyncMock()


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(parsers.parse('source "{source_id}" "{prior_lookup_state}"'))
def source_with_prior_state(ctx, source_id, prior_lookup_state):
    """
    Configure registry mock based on prior lookup state from Examples table.

    TODO:
      if "last performed a bulk lookup at" in prior_lookup_state:
          timestamp = extract timestamp from string
          registry returns LookupState(source_id, last_snapshot=timestamp)
      elif "has never performed a bulk lookup" in prior_lookup_state:
          registry returns None
      elif "has no resolution requests" in prior_lookup_state:
          registry raises SourceNotFoundError
      elif "Decision Store is unavailable" in prior_lookup_state:
          decision_store raises RepositoryConnectionError
    """
    ctx["source_id"] = source_id
    ctx["prior_lookup_state"] = prior_lookup_state


@given(
    parsers.parse(
        'the Decision Store contains {total:d} decisions for source "{source_id}" '
        "with {changed:d} updated since the last lookup"
    )
)
def decision_store_has_decisions(ctx, total, source_id, changed):
    """
    TODO: Configure decision_store mock to return changed decisions for delta query.
    """
    ctx["total_decisions"] = total
    ctx["changed_count"] = changed


@given(parsers.parse('source "{source_id}" last performed a bulk lookup at {timestamp}'))
def source_last_lookup(ctx, source_id, timestamp):
    """
    For the read-only scenario.

    TODO: Configure registry with lookup state.
    """
    ctx["source_id"] = source_id


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(parsers.parse('a bulk lookup is requested for source "{source_id}"'))
def request_bulk_lookup(ctx, source_id):
    """
    TODO: try:
              ctx["result"] = await service.refresh_bulk(source_id)
          except (...) as exc:
              ctx["raised_exception"] = exc
    """
    ctx["source_id"] = source_id
    ctx["result"] = None  # TODO: replace with real service call
    ctx["raised_exception"] = None


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.parse("{count:d} cluster assignments are returned"))
def n_assignments_returned(ctx, count):
    """
    TODO: assert len(ctx["result"].items) == count
    """
    assert True  # TODO: implement


@then(parsers.parse("{notification_date_action}"))
def assert_notification_date_action(ctx, notification_date_action):
    """
    Assert last notification date action from Examples table.

    TODO:
      if "is advanced" in notification_date_action:
          ctx["registry_service"].advance_lookup.assert_called_once()
      elif "is created" in notification_date_action:
          ctx["registry_service"].advance_lookup.assert_called_once()
    """
    assert True  # TODO: implement


@then(parsers.parse('a "{error_type}" error is returned'))
def typed_error_returned(ctx, error_type):
    """
    TODO: assert ctx["raised_exception"] is not None
    """
    assert True  # TODO: implement


@then("the last notification date is not modified")
def notification_date_not_modified(ctx):
    """
    TODO: ctx["registry_service"].advance_lookup.assert_not_called()
    """
    assert True  # TODO: implement


@then("no resolution requests are published to the ERE")
def no_ere_publish(ctx):
    """
    TODO: ctx["publish_service"].publish_request.assert_not_called()
    """
    assert True  # TODO: implement


@then("no decisions are written to the Decision Store")
def no_decision_writes(ctx):
    """
    TODO: ctx["decision_store_service"].store_decision.assert_not_called()
    """
    assert True  # TODO: implement


@then("no requests are registered in the Request Registry")
def no_registration(ctx):
    """
    TODO: ctx["registry_service"].register_resolution_request.assert_not_called()
    """
    assert True  # TODO: implement
