"""
Step definitions for: bulk_lookup_and_snapshot_management.feature

Feature: Lookup Request Registration and Snapshot State Management
  Covers seven behaviours:
    1. Registering a bulk lookup request creates an append-only LookupRequestRecord.
    2. Multiple bulk lookups from the same source accumulate without overwriting.
    3. Registering a single lookup request creates an append-only LookupRequestRecord.
    4. Single and bulk lookup records from the same source coexist independently.
    5. Advancing the snapshot watermark for a known source updates LookupState.last_snapshot.
    6. Advancing the snapshot to the current or earlier time raises SnapshotRegressionError.
    7. Retrieving lookup state for known/unknown sources returns the correct result.

  These steps call RequestRegistryService with a mocked or in-memory repository.
  No real MongoDB connection is required for unit-level BDD scenarios.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, create_autospec

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from ers.commons.adapters.hasher import SHA256ContentHasher
from ers.request_registry.adapters.records_repository import (
    LookupRequestRepository,
    LookupStateRepository,
    ResolutionRequestRepository,
)
from ers.request_registry.domain.records import (
    LookupRequestRecord,
    LookupRequestType,
    LookupState,
)
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


@scenario(FEATURE_FILE, "Register a bulk lookup request")
def test_register_bulk_lookup_request():
    """Bind the 'Register a bulk lookup request' scenario outline."""
    pass


@scenario(FEATURE_FILE, "Register multiple bulk lookup requests from the same source")
def test_register_multiple_bulk_lookups():
    """Bind the 'Register multiple bulk lookup requests from the same source' outline."""
    pass


@scenario(FEATURE_FILE, "Register a single lookup request")
def test_register_single_lookup_request():
    """Bind the 'Register a single lookup request' scenario outline."""
    pass


@scenario(FEATURE_FILE, "Register lookup requests of different types from the same source")
def test_register_mixed_lookup_types():
    """Bind the 'Register lookup requests of different types' scenario outline."""
    pass


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
    """
    Instantiate the RequestRegistryService with mocked repositories and a real hasher.

    All three repositories are created with create_autospec to catch wrong method
    signatures.  SHA256ContentHasher is used as-is (pure function — no I/O).
    """
    resolution_repo = create_autospec(ResolutionRequestRepository, instance=True)
    lookup_repo = create_autospec(LookupStateRepository, instance=True)
    lookup_request_repo = create_autospec(LookupRequestRepository, instance=True)

    # Default: no existing lookup state
    lookup_repo.get.return_value = None

    service = RequestRegistryService(
        resolution_repo=resolution_repo,
        lookup_repo=lookup_repo,
        lookup_request_repo=lookup_request_repo,
        hasher=SHA256ContentHasher(),
    )

    ctx["resolution_repo"] = resolution_repo
    ctx["lookup_repo"] = lookup_repo
    ctx["lookup_request_repo"] = lookup_request_repo
    ctx["service"] = service
    ctx["stored_lookup_records"] = []  # accumulates all stored LookupRequestRecords


@given("the repository is empty")
def repository_is_empty(ctx):
    """
    Ensure the mocked repository has no existing lookup records or states.

    All read operations return empty collections or None.
    """
    ctx["lookup_request_repo"].find_by_source_id.return_value = []
    ctx["lookup_repo"].get.return_value = None


# ---------------------------------------------------------------------------
# Given — source system and state setup
# ---------------------------------------------------------------------------


@given(parsers.parse('a source system identified by "{source_id}"'))
def a_source_system(ctx, source_id):
    """
    Record the source_id under test in the shared context.

    No repository interaction at this stage.
    """
    ctx["source_id"] = source_id


@given(parsers.parse('a bulk lookup request has already been registered for "{source_id}"'))
def bulk_lookup_already_registered(ctx, source_id):
    """
    Pre-seed the mocked repository with one existing LookupRequestRecord for
    the given source_id, simulating a prior successful bulk registration.
    """
    existing = LookupRequestRecord(
        source_id=source_id,
        requested_at=datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC),
        request_type=LookupRequestType.BULK,
    )
    ctx["existing_lookup_record"] = existing
    ctx["stored_lookup_records"].append(existing)
    ctx["lookup_request_repo"].find_by_source_id.return_value = [existing]


@given(parsers.parse('the existing last_snapshot for "{source_id}" is "{existing_last_snapshot}"'))
def current_lookup_state(ctx, source_id, existing_last_snapshot):
    """
    Configure the mocked repository's get return value to match the scenario's
    existing state.

    Handles two cases:
      - "(none)": get returns None (new source, no prior state).
      - ISO datetime string: get returns a LookupState with last_snapshot parsed
        from the string.
    """
    ctx["source_id"] = source_id
    ctx["existing_last_snapshot_str"] = existing_last_snapshot

    if existing_last_snapshot == "(none)":
        ctx["lookup_repo"].get.return_value = None
        ctx["existing_lookup_state"] = None
    else:
        existing_ts = datetime.fromisoformat(existing_last_snapshot)
        existing_state = LookupState(
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
    """
    Pre-configure the repository to return a LookupState with last_snapshot
    set to snapshot_time, simulating a prior successful snapshot advance.

    Used in the 'Retrieve the current lookup state for a known source' scenario.
    """
    ts = datetime.fromisoformat(snapshot_time)
    state = LookupState(
        source_id=source_id,
        last_snapshot=ts,
        updated_at=ts,
    )
    ctx["known_lookup_state"] = state
    ctx["lookup_repo"].get.return_value = state


@given(parsers.parse('no lookup state exists for "{source_id}"'))
def no_lookup_state_exists(ctx, source_id):
    """
    Confirm that get returns None for source_id (unknown source).
    """
    ctx["lookup_repo"].get.return_value = None


# ---------------------------------------------------------------------------
# When — trigger service calls
# ---------------------------------------------------------------------------


@when(parsers.parse('a bulk lookup request is registered for "{source_id}"'))
def register_bulk_lookup_request(ctx, source_id):
    """
    Call RequestRegistryService.register_lookup_request with BULK type.

    Configures store to return the record it receives (identity side-effect).
    Captures the returned LookupRequestRecord or any raised exception.
    """
    ctx["lookup_request_repo"].store.side_effect = lambda r: r

    try:
        ctx["result"] = asyncio.run(
            ctx["service"].register_lookup_request(source_id, LookupRequestType.BULK)
        )
        ctx["stored_lookup_records"].append(ctx["result"])
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when(parsers.parse('a single lookup request is registered for "{source_id}"'))
def register_single_lookup_request(ctx, source_id):
    """
    Call RequestRegistryService.register_lookup_request with SINGLE type.

    Captures the returned LookupRequestRecord or any raised exception.
    """
    ctx["lookup_request_repo"].store.side_effect = lambda r: r

    try:
        ctx["result"] = asyncio.run(
            ctx["service"].register_lookup_request(source_id, LookupRequestType.SINGLE)
        )
        ctx["stored_lookup_records"].append(ctx["result"])
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when(parsers.parse('a second bulk lookup request is registered for "{source_id}"'))
def register_second_bulk_lookup(ctx, source_id):
    """
    Register a second bulk lookup for a source that already has one record.

    After this call, stored_lookup_records must contain two entries for the
    source_id. The earlier record must remain unmodified.
    """
    ctx["lookup_request_repo"].store.side_effect = lambda r: r

    try:
        ctx["result"] = asyncio.run(
            ctx["service"].register_lookup_request(source_id, LookupRequestType.BULK)
        )
        ctx["stored_lookup_records"].append(ctx["result"])
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when(parsers.parse('the snapshot is advanced to "{snapshot_time}"'))
def advance_snapshot(ctx, snapshot_time):
    """
    Call RequestRegistryService.advance_snapshot with the given timestamp.

    Two outcomes are possible:
      - Success: returns updated LookupState with last_snapshot == snapshot_time.
      - SnapshotRegressionError: raised when snapshot_time <= current last_snapshot.

    Captures the result or exception in ctx without letting the exception propagate.
    """
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
    """
    Call RequestRegistryService.get_lookup_state for the given source_id.

    Captures the returned LookupState or None in ctx.
    """
    try:
        ctx["result"] = asyncio.run(ctx["service"].get_lookup_state(source_id))
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


# ---------------------------------------------------------------------------
# Then — assert outcomes
# ---------------------------------------------------------------------------


@then(parsers.parse('a lookup request record is returned for "{source_id}"'))
def lookup_request_record_returned(ctx, source_id):
    """
    Assert that the service returned a LookupRequestRecord (not None, not an
    exception) for the given source_id.
    """
    assert ctx["raised_exception"] is None, (
        f"Expected a record but got exception: {ctx['raised_exception']}"
    )
    assert ctx["result"] is not None, "Expected a LookupRequestRecord but got None"
    assert isinstance(ctx["result"], LookupRequestRecord), (
        f"Expected LookupRequestRecord, got {type(ctx['result'])}"
    )
    assert ctx["result"].source_id == source_id


@then("the lookup request record has request type BULK")
def lookup_record_has_bulk_type(ctx):
    """Assert that the returned LookupRequestRecord.request_type is LookupRequestType.BULK."""
    assert ctx["result"].request_type == LookupRequestType.BULK, (
        f"Expected BULK, got {ctx['result'].request_type}"
    )


@then("the lookup request record has request type SINGLE")
def lookup_record_has_single_type(ctx):
    """Assert that the returned LookupRequestRecord.request_type is LookupRequestType.SINGLE."""
    assert ctx["result"].request_type == LookupRequestType.SINGLE, (
        f"Expected SINGLE, got {ctx['result'].request_type}"
    )


@then("the lookup request record has a requested_at timestamp set to the current UTC time")
def lookup_record_requested_at_is_utc_now(ctx):
    """
    Assert that requested_at on the returned record is a timezone-aware UTC
    datetime that is within 2 seconds of now.
    """
    record = ctx["result"]
    assert record.requested_at.tzinfo is not None
    delta = abs(datetime.now(UTC) - record.requested_at)
    assert delta < timedelta(seconds=2), (
        f"requested_at {record.requested_at} is more than 2 seconds away from now"
    )


@then(parsers.parse('both lookup request records exist in the repository for "{source_id}"'))
def both_lookup_records_exist(ctx, source_id):
    """
    Assert that two records have been stored for source_id:
    the one created in the Given step and the one created in the When step.
    """
    source_records = [r for r in ctx["stored_lookup_records"] if r.source_id == source_id]
    assert len(source_records) == 2, (
        f"Expected 2 lookup records for {source_id}, found {len(source_records)}"
    )
    assert all(r.source_id == source_id for r in source_records)


@then("the earlier record is not modified")
def earlier_record_not_modified(ctx):
    """
    Assert that the existing_lookup_record captured in the Given step is
    identical to the first record in stored_lookup_records — confirming
    append-only behaviour (the original record object is unchanged).
    """
    existing = ctx["existing_lookup_record"]
    # The existing record must still be present and unmodified in stored_lookup_records
    assert existing in ctx["stored_lookup_records"], (
        "The earlier lookup record was not found in stored records"
    )
    # Verify its fields are unchanged (frozen model ensures immutability)
    assert existing.request_type == LookupRequestType.BULK
    assert existing.requested_at == datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)


@then(parsers.parse('the lookup state for "{source_id}" has last_snapshot "{snapshot_time}"'))
def lookup_state_has_new_last_snapshot(ctx, source_id, snapshot_time):
    """
    Assert that the returned LookupState has last_snapshot equal to snapshot_time.
    """
    expected_ts = datetime.fromisoformat(snapshot_time)
    assert ctx["result"] is not None, "Expected a LookupState but got None"
    assert isinstance(ctx["result"], LookupState), (
        f"Expected LookupState, got {type(ctx['result'])}"
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
    """
    Assert that the repository's stored last_snapshot for source_id is unchanged
    after a failed regression attempt — confirmed by checking upsert was not called.
    """
    expected_ts = datetime.fromisoformat(existing_last_snapshot)
    # upsert must not have been called — the existing state is unchanged
    ctx["lookup_repo"].upsert.assert_not_called()
    # Verify the existing state in ctx still holds the expected timestamp
    existing_state = ctx.get("existing_lookup_state")
    assert existing_state is not None
    assert existing_state.last_snapshot == expected_ts


@then(parsers.parse('the lookup state is returned with last_snapshot "{last_snapshot}"'))
def lookup_state_returned_with_last_snapshot(ctx, last_snapshot):
    """
    Assert that get_lookup_state returned a LookupState whose last_snapshot
    equals the given ISO datetime string.
    """
    expected_ts = datetime.fromisoformat(last_snapshot)
    assert ctx["result"] is not None, "Expected a LookupState but got None"
    assert isinstance(ctx["result"], LookupState), (
        f"Expected LookupState, got {type(ctx['result'])}"
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
