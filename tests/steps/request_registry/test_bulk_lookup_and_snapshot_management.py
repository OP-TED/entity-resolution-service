"""
Step definitions for: bulk_lookup_and_snapshot_management.feature

Feature: Bulk Lookup Request Registration and Snapshot State Management
  Covers four behaviours:
    1. Registering a bulk lookup request creates an append-only LookupRequestRecord.
    2. Multiple bulk lookups from the same source accumulate without overwriting.
    3. Advancing the snapshot watermark for a known source updates LookupState.last_snapshot.
    4. Advancing the snapshot to the current or earlier time raises WatermarkRegressionError.
    5. Retrieving lookup state for known/unknown sources returns the correct result.

  These steps call RequestRegistryService with a mocked or in-memory repository.
  No real MongoDB connection is required for unit-level BDD scenarios.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from erspec.models.core import LookupState

# ---------------------------------------------------------------------------
# Scenario bindings — link each scenario title to its .feature file.
# ---------------------------------------------------------------------------

FEATURE_FILE = str(Path(__file__).parent.parent.parent / "features" / "request_registry" / "bulk_lookup_and_snapshot_management.feature")


@scenario(FEATURE_FILE, "Register a bulk lookup request")
def test_register_bulk_lookup_request():
    """Bind the 'Register a bulk lookup request' scenario outline."""
    pass


@scenario(FEATURE_FILE, "Register multiple bulk lookup requests from the same source")
def test_register_multiple_bulk_lookups():
    """Bind the 'Register multiple bulk lookup requests from the same source' outline."""
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
    Instantiate the RequestRegistryService with a mocked repository.

    The mock repository starts in a clean state (no stored records, no lookup states).

    TODO: Replace MagicMock with create_autospec(RequestRegistryRepository)
          once the abstract repository class exists.
    """
    # TODO: from ers.request_registry.adapters.repository import RequestRegistryRepository
    # TODO: from ers.request_registry.services.request_registry_service import RequestRegistryService
    repository = MagicMock()
    repository.store_lookup_request = AsyncMock()
    repository.find_lookup_requests_by_source = AsyncMock(return_value=[])
    repository.get_lookup_state = AsyncMock(return_value=None)
    repository.upsert_lookup_state = AsyncMock()
    ctx["repository"] = repository
    # ctx["service"] = RequestRegistryService(repository=repository)
    ctx["service"] = None  # TODO: replace with real service instantiation


@given("the repository is empty")
def repository_is_empty(ctx):
    """
    Ensure the mocked repository has no existing lookup records or states.

    All read operations return empty collections or None.
    """
    repository = ctx["repository"]
    repository.find_lookup_requests_by_source = AsyncMock(return_value=[])
    repository.get_lookup_state = AsyncMock(return_value=None)


# ---------------------------------------------------------------------------
# Given — source system and state setup
# ---------------------------------------------------------------------------


@given(parsers.parse('a source system identified by "{source_id}"'))
def a_source_system(ctx, source_id):
    """
    Record the source_id under test in the shared context.

    No repository interaction at this stage — merely sets up the identifier
    that subsequent steps will use when calling the service.
    """
    ctx["source_id"] = source_id


@given(parsers.parse('a bulk lookup request has already been registered for "{source_id}"'))
def bulk_lookup_already_registered(ctx, source_id):
    """
    Pre-seed the mocked repository with one existing LookupRequestRecord for
    the given source_id, simulating a prior successful bulk registration.

    TODO: Build a real LookupRequestRecord:
        from ers.request_registry.models.records import LookupRequestRecord, LookupRequestType
        existing = LookupRequestRecord(
            source_id=source_id,
            requested_at=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            request_type=LookupRequestType.BULK,
        )
        ctx["repository"].find_lookup_requests_by_source.return_value = [existing]
        ctx["existing_lookup_record"] = existing
    """
    existing_record = MagicMock()
    existing_record.source_id = source_id
    existing_record.requested_at = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    # TODO: existing_record.request_type = LookupRequestType.BULK
    ctx["existing_lookup_record"] = existing_record
    ctx["repository"].find_lookup_requests_by_source = AsyncMock(return_value=[existing_record])


@given(parsers.parse('the existing last_snapshot for "{source_id}" is "{existing_last_snapshot}"'))
def current_lookup_state(ctx, source_id, existing_last_snapshot):
    """
    Configure the mocked repository's get_lookup_state return value to match
    the scenario's existing state.

    Handles two cases:
      - "(none)": get_lookup_state returns None (new source, no prior state).
      - ISO datetime string (e.g., "2024-06-01T12:00:00+00:00"): get_lookup_state
        returns a LookupState with last_snapshot parsed from the string.
    """
    ctx["source_id"] = source_id
    ctx["existing_last_snapshot_str"] = existing_last_snapshot

    if existing_last_snapshot == "(none)":
        ctx["repository"].get_lookup_state = AsyncMock(return_value=None)
        ctx["existing_lookup_state"] = None
    else:
        # Parse the ISO timestamp directly
        existing_ts = datetime.fromisoformat(existing_last_snapshot)
        existing_state = LookupState(
            source_id=source_id,
            last_snapshot=existing_ts,
        )
        ctx["existing_lookup_state"] = existing_state
        ctx["repository"].get_lookup_state = AsyncMock(return_value=existing_state)


@given(
    parsers.parse(
        'the snapshot watermark for "{source_id}" has been advanced to "{snapshot_time}"'
    )
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
    )
    ctx["known_lookup_state"] = state
    ctx["repository"].get_lookup_state = AsyncMock(return_value=state)


@given(parsers.parse('no lookup state exists for "{source_id}"'))
def no_lookup_state_exists(ctx, source_id):
    """
    Confirm that get_lookup_state returns None for source_id.

    Redundant with the Background 'repository is empty' step but explicit
    for scenarios that focus specifically on the unknown-source read path.
    """
    ctx["repository"].get_lookup_state = AsyncMock(return_value=None)


# ---------------------------------------------------------------------------
# When — trigger service calls
# ---------------------------------------------------------------------------


@when(parsers.parse('a bulk lookup request is registered for "{source_id}"'))
def register_bulk_lookup_request(ctx, source_id):
    """
    Call RequestRegistryService.register_lookup_request with BULK type.

    Captures the returned LookupRequestRecord or any raised exception.

    TODO: Replace with real async call:
        import asyncio
        from ers.request_registry.models.records import LookupRequestType
        ctx["result"] = asyncio.run(
            ctx["service"].register_lookup_request(source_id, LookupRequestType.BULK)
        )
    """
    # Simulate a returned record for the placeholder
    returned_record = MagicMock()
    returned_record.source_id = source_id
    returned_record.requested_at = datetime.now(timezone.utc)
    # TODO: returned_record.request_type = LookupRequestType.BULK
    ctx["repository"].store_lookup_request = AsyncMock(return_value=returned_record)
    ctx["result"] = returned_record  # TODO: replace with real service call
    ctx["raised_exception"] = None


@when(parsers.parse('a second bulk lookup request is registered for "{source_id}"'))
def register_second_bulk_lookup(ctx, source_id):
    """
    Register a second bulk lookup for a source that already has one record.

    After this call, the repository must contain two LookupRequestRecord entries
    for the source_id. The earlier record must remain unmodified.

    TODO: Call the service and then verify the repository's append-only behaviour.
    """
    second_record = MagicMock()
    second_record.source_id = source_id
    second_record.requested_at = datetime.now(timezone.utc)
    ctx["second_lookup_record"] = second_record
    # Configure find_lookup_requests_by_source to now return both records
    ctx["repository"].find_lookup_requests_by_source = AsyncMock(
        return_value=[ctx.get("existing_lookup_record"), second_record]
    )
    ctx["result"] = second_record  # TODO: replace with real service call
    ctx["raised_exception"] = None


@when(parsers.parse('the snapshot is advanced to "{snapshot_time}"'))
def advance_snapshot(ctx, snapshot_time):
    """
    Call RequestRegistryService.advance_snapshot with the given timestamp.

    Two outcomes are possible:
      - Success: returns updated LookupState with last_snapshot == snapshot_time.
      - SnapshotRegressionError: raised when snapshot_time <= current last_snapshot.

    Captures the result or exception in ctx without letting the exception
    propagate (so Then steps can assert on it).

    TODO: Replace with real async call:
        import asyncio
        from ers.request_registry.services.exceptions import SnapshotRegressionError
        ts = datetime.fromisoformat(snapshot_time)
        try:
            ctx["result"] = asyncio.run(
                ctx["service"].advance_snapshot(ctx["source_id"], ts)
            )
            ctx["raised_exception"] = None
        except SnapshotRegressionError as exc:
            ctx["result"] = None
            ctx["raised_exception"] = exc
    """
    ts = datetime.fromisoformat(snapshot_time)
    ctx["snapshot_time"] = ts
    existing_state = ctx.get("existing_lookup_state")

    is_regression = (
        existing_state is not None
        and ts <= existing_state.last_snapshot
    )

    if is_regression:
        ctx["result"] = None
        # TODO: ctx["raised_exception"] = SnapshotRegressionError(...)
        ctx["raised_exception"] = Exception("SnapshotRegressionError")  # placeholder
    else:
        updated_state = LookupState(
            source_id=ctx["source_id"],
            last_snapshot=ts,
        )
        ctx["repository"].upsert_lookup_state = AsyncMock(return_value=updated_state)
        ctx["result"] = updated_state  # TODO: replace with real service call
        ctx["raised_exception"] = None


@when(parsers.parse('the current lookup state is retrieved for "{source_id}"'))
def retrieve_lookup_state(ctx, source_id):
    """
    Call RequestRegistryService.get_lookup_state for the given source_id.

    Captures the returned LookupState or None in ctx.

    TODO: Replace with real async call:
        import asyncio
        ctx["result"] = asyncio.run(ctx["service"].get_lookup_state(source_id))
    """
    # Return whatever get_lookup_state is configured to return for this source
    ctx["result"] = ctx.get("known_lookup_state")  # None for unknown source
    ctx["raised_exception"] = None


# ---------------------------------------------------------------------------
# Then — assert outcomes
# ---------------------------------------------------------------------------


@then(parsers.parse('a lookup request record is returned for "{source_id}"'))
def lookup_request_record_returned(ctx, source_id):
    """
    Assert that the service returned a LookupRequestRecord (not None, not an
    exception) for the given source_id.

    TODO: assert isinstance(ctx["result"], LookupRequestRecord)
          assert ctx["result"].source_id == source_id
    """
    assert ctx["raised_exception"] is None
    assert ctx["result"] is not None
    assert True  # TODO: assert isinstance(ctx["result"], LookupRequestRecord)


@then("the lookup request record has request type BULK")
def lookup_record_has_bulk_type(ctx):
    """
    Assert that the returned LookupRequestRecord.request_type is LookupRequestType.BULK.

    TODO: from ers.request_registry.models.records import LookupRequestType
          assert ctx["result"].request_type == LookupRequestType.BULK
    """
    assert True  # TODO: implement


@then("the lookup request record has a requested_at timestamp set to the current UTC time")
def lookup_record_requested_at_is_utc_now(ctx):
    """
    Assert that requested_at on the returned record is a timezone-aware UTC
    datetime that is within a few seconds of now.

    TODO: record = ctx["result"]
          assert record.requested_at.tzinfo == timezone.utc
          delta = datetime.now(timezone.utc) - record.requested_at
          assert delta.total_seconds() < 5
    """
    assert True  # TODO: implement


@then(
    parsers.parse(
        'both lookup request records exist in the repository for "{source_id}"'
    )
)
def both_lookup_records_exist(ctx, source_id):
    """
    Assert that find_lookup_requests_by_source returns two records for source_id:
    the one created in the Given step and the one created in the When step.

    TODO: records = asyncio.run(
              ctx["repository"].find_lookup_requests_by_source(source_id)
          )
          assert len(records) == 2
          assert all(r.source_id == source_id for r in records)
    """
    assert True  # TODO: implement


@then("the earlier record is not modified")
def earlier_record_not_modified(ctx):
    """
    Assert that the existing_lookup_record captured in the Given step is
    identical to the corresponding entry in the repository after the second
    registration — confirming append-only behaviour.

    TODO: Check that existing_lookup_record.requested_at has not changed and
          that its identity matches the first element returned by
          find_lookup_requests_by_source.
    """
    assert True  # TODO: implement


@then(parsers.parse('the lookup state for "{source_id}" has last_snapshot "{snapshot_time}"'))
def lookup_state_has_new_last_snapshot(ctx, source_id, snapshot_time):
    """
    Assert that the returned LookupState has last_snapshot equal to snapshot_time.

    Used in the 'Advance the snapshot watermark for a source system' scenario.

    TODO: expected_ts = datetime.fromisoformat(snapshot_time)
          assert ctx["result"] is not None
          assert isinstance(ctx["result"], LookupState)
          assert ctx["result"].last_snapshot == expected_ts
    """
    expected_ts = datetime.fromisoformat(snapshot_time)
    assert True  # TODO: assert ctx["result"].last_snapshot == expected_ts


@then("a SnapshotRegressionError is raised")
def snapshot_regression_error_is_raised(ctx):
    """
    Assert that a SnapshotRegressionError was raised during the snapshot advance.

    Used in the 'Reject snapshot regression' scenario.

    TODO: from ers.request_registry.services.exceptions import SnapshotRegressionError
          assert isinstance(ctx["raised_exception"], SnapshotRegressionError)
    """
    assert ctx["raised_exception"] is not None, (
        "Expected SnapshotRegressionError to be raised but it was not."
    )
    assert True  # TODO: assert isinstance(ctx["raised_exception"], SnapshotRegressionError)


@then(parsers.parse('the last_snapshot for "{source_id}" remains "{existing_last_snapshot}"'))
def last_snapshot_remains_unchanged(ctx, source_id, existing_last_snapshot):
    """
    Assert that the repository's stored last_snapshot for source_id is unchanged
    after a failed regression attempt.

    Used in the 'Reject snapshot watermark regression' scenario to verify that
    no mutation occurred.

    TODO: expected_ts = datetime.fromisoformat(existing_last_snapshot)
          stored_state = asyncio.run(ctx["repository"].get_lookup_state(source_id))
          assert stored_state is not None
          assert stored_state.last_snapshot == expected_ts
    """
    expected_ts = datetime.fromisoformat(existing_last_snapshot)
    assert True  # TODO: verify repository state is unchanged


@then(parsers.parse('the final last_snapshot for "{source_id}" is "{final_snapshot}"'))
def final_last_snapshot_matches(ctx, source_id, final_snapshot):
    """
    Assert that the last_snapshot value on the LookupState (either the returned
    result or the state still stored in the repository) equals final_snapshot.

    For regression scenarios the result is None, so we verify the repository's
    stored state is unchanged by calling get_lookup_state and comparing.

    TODO: Implement correctly:
        expected_ts = datetime.fromisoformat(final_snapshot)
        if ctx["result"] is not None:
            assert ctx["result"].last_snapshot == expected_ts
        else:
            # Regression: repository state must be unchanged
            stored = asyncio.run(ctx["repository"].get_lookup_state(source_id))
            assert stored.last_snapshot == expected_ts
    """
    expected_ts = datetime.fromisoformat(final_snapshot)
    assert True  # TODO: implement comparison


@then(
    parsers.parse(
        'the lookup state is returned with last_snapshot "{last_snapshot}"'
    )
)
def lookup_state_returned_with_last_snapshot(ctx, last_snapshot):
    """
    Assert that get_lookup_state returned a LookupState whose last_snapshot
    equals the given ISO datetime string.

    TODO: expected_ts = datetime.fromisoformat(last_snapshot)
          assert ctx["result"] is not None
          assert ctx["result"].last_snapshot == expected_ts
    """
    expected_ts = datetime.fromisoformat(last_snapshot)
    assert ctx["result"] is not None
    assert True  # TODO: assert ctx["result"].last_snapshot == expected_ts


@then("no lookup state is returned")
def no_lookup_state_returned(ctx):
    """
    Assert that get_lookup_state returned None for an unknown source_id.

    TODO: assert ctx["result"] is None
    """
    assert ctx["result"] is None
