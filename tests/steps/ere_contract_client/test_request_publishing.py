"""
Step definitions for: request_publishing.feature

Feature: Publish Resolution Requests to ERE via the Unified Resolution Envelope
  Covers four behaviours:
    1. All optional constraint combinations (none, proposed, excluded, both).
    2. Singleton proposal with SHA256-derived provisional cluster.
    3. Auto-generation of missing metadata (ere_request_id, timestamp).
    4. Duplicate publish under at-least-once semantics.

  These steps call the EREPublishService with a mocked adapter.
  No real Redis connection is required for unit-level BDD scenarios.
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
    / "features"
    / "ere_contract_client"
    / "request_publishing.feature"
)


@scenario(FEATURE_FILE, "Publish a resolution request with optional constraint fields")
def test_publish_with_optional_fields():
    pass


@scenario(FEATURE_FILE, "Publish a singleton proposal for a provisional cluster")
def test_publish_singleton_proposal():
    pass


@scenario(FEATURE_FILE, "Auto-generate missing request metadata before publishing")
def test_auto_generate_metadata():
    pass


@scenario(FEATURE_FILE, "Publishing the same request twice succeeds under at-least-once semantics")
def test_duplicate_publish():
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


@given("the ERE Contract Client is available")
def ere_contract_client_available(ctx):
    """
    Set up the EREPublishService with a mocked adapter.

    TODO: Replace with create_autospec(RedisEREAdapter)
    """
    adapter = MagicMock()
    adapter.push_request = AsyncMock(return_value=1)
    adapter.ping = AsyncMock(return_value=True)
    ctx["adapter"] = adapter
    ctx["service"] = None  # TODO: EREPublishService(adapter)


@given("the messaging channel is reachable")
def messaging_channel_reachable(ctx):
    """Confirm the mock adapter simulates a reachable channel."""
    ctx["adapter"].push_request = AsyncMock(return_value=1)


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        'a valid entity mention with correlation triad '
        '("{source_id}", "{request_id}", "Organization")'
    )
)
def valid_entity_mention(ctx, source_id, request_id):
    """
    Build a valid EntityMentionResolutionRequest with the given triad.

    TODO: Build a real EntityMention + EntityMentionIdentifier from erspec.
    """
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = "Organization"


@given(
    parsers.parse(
        'the request includes proposed placements "{proposed}" '
        'and excluded clusters "{excluded}"'
    )
)
def request_with_optional_fields(ctx, proposed, excluded):
    """
    Configure proposed placements and excluded clusters on the request.

    TODO: Parse comma-separated lists (or None if "none") and set on request:
      request.proposed_cluster_ids = [p.strip() for p in proposed.split(",")]
      request.excluded_cluster_ids = [e.strip() for e in excluded.split(",")]
    """
    ctx["proposed_placements"] = (
        None if proposed == "none"
        else [p.strip() for p in proposed.split(",")]
    )
    ctx["excluded_clusters"] = (
        None if excluded == "none"
        else [e.strip() for e in excluded.split(",")]
    )


@given(
    "the request includes a single proposed placement "
    "using the SHA256-derived provisional cluster"
)
def request_with_singleton_proposal(ctx):
    """
    Configure the request with a single proposed placement = provisional cluster ID.

    TODO: provisional_id = derive_provisional_cluster_id(identifier)
          request.proposed_cluster_ids = [provisional_id]
    """
    ctx["singleton_proposal"] = True


@given(
    parsers.parse(
        'the resolution request has "{field}" not set'
    )
)
def request_field_not_set(ctx, field):
    """
    Configure the request to have the specified field absent.

    TODO: Build request with field explicitly set to None.
    """
    ctx["unset_field"] = field


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the resolution request is published")
def publish_request(ctx):
    """
    Call EREPublishService.publish_request.

    TODO: ctx["ere_request_id"] = await service.publish_request(request)
          ctx["publish_count"] = ctx.get("publish_count", 0) + 1
    """
    ctx["publish_count"] = ctx.get("publish_count", 0) + 1
    ctx["result"] = None  # TODO: replace with real service call
    ctx["raised_exception"] = None


@when("the same resolution request is published again")
def publish_request_again(ctx):
    """
    Call EREPublishService.publish_request with the same request a second time.

    TODO: ctx["ere_request_id_2"] = await service.publish_request(request)
          ctx["publish_count"] = ctx.get("publish_count", 0) + 1
    """
    ctx["publish_count"] = ctx.get("publish_count", 0) + 1
    ctx["result_2"] = None  # TODO: replace with real service call
    ctx["raised_exception"] = None


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the request is enqueued on the messaging channel")
def request_enqueued(ctx):
    """
    TODO: ctx["adapter"].push_request.assert_called()
    """
    assert True  # TODO: implement


@then("the published request contains the complete correlation triad")
def published_request_has_triad(ctx):
    """
    TODO: Inspect the serialized request passed to adapter.push_request
          and verify source_id, request_id, entity_type are all present.
    """
    assert True  # TODO: implement


@then("the ere_request_id is present in the published request")
def ere_request_id_present(ctx):
    """
    TODO: Inspect the published request and assert ere_request_id is not None.
    """
    assert True  # TODO: implement


@then("the proposed placements contain exactly the provisional cluster identifier")
def proposed_contains_provisional(ctx):
    """
    TODO: assert len(request.proposed_cluster_ids) == 1
          assert request.proposed_cluster_ids[0] == derive_provisional_cluster_id(identifier)
    """
    assert True  # TODO: implement


@then(
    parsers.parse(
        'the published request has "{field}" auto-populated'
    )
)
def field_auto_populated(ctx, field):
    """
    Assert the specified field was auto-generated.

    TODO:
      if field == "ere_request_id":
          assert request.ere_request_id is not None (UUID format)
      elif field == "timestamp":
          assert request.timestamp is not None (recent UTC)
    """
    assert True  # TODO: implement


@then("both requests are enqueued on the messaging channel")
def both_requests_enqueued(ctx):
    """
    Assert the adapter was called twice (at-least-once allows duplicates).

    TODO: assert ctx["adapter"].push_request.call_count == 2
    """
    assert True  # TODO: implement
