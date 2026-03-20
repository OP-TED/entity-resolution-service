"""
Step definitions for: bulk_lookup_and_snapshot_management.feature

Feature: Snapshot State Management
  Covers four behaviours:
    1. Advancing the snapshot watermark for a known source updates LookupRequestRecord.last_snapshot.
    2. Advancing the snapshot to the current or earlier time raises SnapshotRegressionError.
    3. Retrieving lookup state for known sources returns the correct result.
    4. Retrieving lookup state for unknown sources returns nothing.

  These steps call RequestRegistryService with a mocked or in-memory repository.
  No real MongoDB connection is required for unit-level BDD scenarios.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from ers.commons.adapters.hasher import SHA256ContentHasher
from ers.request_registry.adapters.records_repository import (
    MongoLookupStateRepository,
    MongoResolutionRequestRepository,
)
from ers.request_registry.domain.records import LookupRequestRecord
from ers.request_registry.services.exceptions import SnapshotRegressionError
from ers.request_registry.services.request_registry_service import RequestRegistryService

# ---------------------------------------------------------------------------
# Scenario bindings — link each scenario title to its .feature file.
# ---------------------------------------------------------------------------

FEATURE_FILE = str(
    Path(__file__).parent.parent.parent
    / "feature"
    / "request_registry"
    / "bulk_lookup_and_snapshot_management.feature"
)


@scenario(FEATURE_FILE, "Advance the snapshot for a source system")
def test_advance_snapshot():
    """Bind the 'Advance the snapshot for a source system' scenario outline."""
    pass


@scenario(FEATURE_FILE, "Reject snapshot regression")
def test_reject_snapshot_regression():
    """Bind the 'Reject snapshot regression' scenario outline."""
    pass


@scenario(FEATURE_FILE, "Retrieve the current lookup state for a known source")
def test_retrieve_lookup_state_known_source():
    """Bind the 'Retrieve the current lookup state for a known source' scenario."""
    pass


@scenario(FEATURE_FILE, "Retrieve lookup state for an unknown source returns nothing")
def test_retrieve_lookup_state_unknown_source():
    """Bind the 'Retrieve lookup state for an unknown source returns nothing' scenario."""
    pass


# ---------------------------------------------------------------------------
# Shared context container
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Shared mutable context for passing state between step functions."""
    return {}


# ---------------------------------------------------------------------------
# Background steps
# ---------------------------------------------------------------------------


@given("the Request Registry service is available")
def request_registry_service_available(ctx):
    """Instantiate the RequestRegistryService with mocked repositories and a real hasher."""
    resolution_repo = create_autospec(MongoResolutionRequestRepository, instance=True)
    lookup_repo = create_autospec(MongoLookupStateRepository, instance=True)

    # Default: no existing lookup state
    lookup_repo.get.return_value = None

    service = RequestRegistryService(
        resolution_repo=resolution_repo,
        lookup_repo=lookup_repo,
        hasher=SHA256ContentHasher(),
    )

    ctx["resolution_repo"] = resolution_repo
    ctx["lookup_repo"] = lookup_repo
    ctx["service"] = service


@given("the repository is empty")
def repository_is_empty(ctx):
    """Ensure the mocked repository has no existing lookup states."""
    ctx["lookup_repo"].get.return_value = None


# ---------------------------------------------------------------------------
# Given — source system and state setup
# ---------------------------------------------------------------------------


@given(parsers.parse('a source system identified by "{source_id}"'))
def a_source_system(ctx, source_id):
    """Record the source_id under test in the shared context."""
    ctx["source_id"] = source_id


@given(parsers.parse('the existing last_snapshot for "{source_id}" is "{existing_last_snapshot}"'))
def current_lookup_state(ctx, source_id, existing_last_snapshot):
    """Configure the mocked repository's get return value to match the scenario's existing state."""
    ctx["source_id"] = source_id
    ctx["existing_last_snapshot_str"] = existing_last_snapshot

    if existing_last_snapshot == "(none)":
        ctx["lookup_repo"].get.return_value = None
        ctx["existing_lookup_state"] = None
    else:
        existing_ts = datetime.fromisoformat(existing_last_snapshot)
        existing_state = LookupRequestRecord(
            source_id=source_id,
            last_snapshot=existing_ts,
            updated_at=existing_ts,
        )
        ctx["existing_lookup_state"] = existing_state
        ctx["lookup_repo"].get.return_value = existing_state


@given(
    parsers.parse('the snapshot watermark for "{source_id}" has been advanced to "{snapshot_time}"')
)
def snapshot_watermark_already_advanced(ctx, source_id, snapshot_time):
    """Pre-configure the repository to return a LookupRequestRecord with last_snapshot set."""
    ts = datetime.fromisoformat(snapshot_time)
    state = LookupRequestRecord(
        source_id=source_id,
        last_snapshot=ts,
        updated_at=ts,
    )
    ctx["known_lookup_state"] = state
    ctx["lookup_repo"].get.return_value = state


@given(parsers.parse('no lookup state exists for "{source_id}"'))
def no_lookup_state_exists(ctx, source_id):
    """Confirm that get returns None for source_id (unknown source)."""
    ctx["lookup_repo"].get.return_value = None


# ---------------------------------------------------------------------------
# When — trigger service calls
# ---------------------------------------------------------------------------


@when(parsers.parse('the snapshot is advanced to "{snapshot_time}"'))
def advance_snapshot(ctx, snapshot_time):
    """Call RequestRegistryService.advance_snapshot with the given timestamp."""
    ts = datetime.fromisoformat(snapshot_time)
    ctx["snapshot_time"] = ts
    ctx["lookup_repo"].upsert.side_effect = lambda s: s

    try:
        ctx["result"] = asyncio.run(
            ctx["service"].advance_snapshot(ctx["source_id"], ts)
        )
        ctx["raised_exception"] = None
    except SnapshotRegressionError as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when(parsers.parse('the current lookup state is retrieved for "{source_id}"'))
def retrieve_lookup_state(ctx, source_id):
    """Call RequestRegistryService.get_lookup_state for the given source_id."""
    try:
        ctx["result"] = asyncio.run(ctx["service"].get_lookup_state(source_id))
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


# ---------------------------------------------------------------------------
# Then — assert outcomes
# ---------------------------------------------------------------------------


@then(parsers.parse('the lookup state for "{source_id}" has last_snapshot "{snapshot_time}"'))
def lookup_state_has_new_last_snapshot(ctx, source_id, snapshot_time):
    """Assert that the returned LookupRequestRecord has last_snapshot equal to snapshot_time."""
    expected_ts = datetime.fromisoformat(snapshot_time)
    assert ctx["result"] is not None, "Expected a LookupRequestRecord but got None"
    assert isinstance(ctx["result"], LookupRequestRecord), (
        f"Expected LookupRequestRecord, got {type(ctx['result'])}"
    )
    assert ctx["result"].last_snapshot == expected_ts, (
        f"Expected last_snapshot={expected_ts}, got {ctx['result'].last_snapshot}"
    )


@then("a SnapshotRegressionError is raised")
def snapshot_regression_error_is_raised(ctx):
    """Assert that a SnapshotRegressionError was raised during the snapshot advance."""
    assert ctx["raised_exception"] is not None, (
        "Expected SnapshotRegressionError to be raised but it was not."
    )
    assert isinstance(ctx["raised_exception"], SnapshotRegressionError), (
        f"Expected SnapshotRegressionError, got {type(ctx['raised_exception'])}"
    )


@then(parsers.parse('the last_snapshot for "{source_id}" remains "{existing_last_snapshot}"'))
def last_snapshot_remains_unchanged(ctx, source_id, existing_last_snapshot):
    """Assert that upsert was not called — the existing state is unchanged."""
    expected_ts = datetime.fromisoformat(existing_last_snapshot)
    ctx["lookup_repo"].upsert.assert_not_called()
    existing_state = ctx.get("existing_lookup_state")
    assert existing_state is not None
    assert existing_state.last_snapshot == expected_ts


@then(parsers.parse('the lookup state is returned with last_snapshot "{last_snapshot}"'))
def lookup_state_returned_with_last_snapshot(ctx, last_snapshot):
    """Assert that get_lookup_state returned a LookupRequestRecord with the expected last_snapshot."""
    expected_ts = datetime.fromisoformat(last_snapshot)
    assert ctx["result"] is not None, "Expected a LookupRequestRecord but got None"
    assert isinstance(ctx["result"], LookupRequestRecord), (
        f"Expected LookupRequestRecord, got {type(ctx['result'])}"
    )
    assert ctx["result"].last_snapshot == expected_ts, (
        f"Expected last_snapshot={expected_ts}, got {ctx['result'].last_snapshot}"
    )


@then("no lookup state is returned")
def no_lookup_state_returned(ctx):
    """Assert that get_lookup_state returned None for an unknown source_id."""
    assert ctx["result"] is None, (
        f"Expected None but got {ctx['result']}"
    )
