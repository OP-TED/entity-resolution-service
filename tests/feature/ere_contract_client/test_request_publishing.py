"""
Step definitions for: request_publishing.feature

Feature: Publish Resolution Requests to ERE via the Unified Resolution Envelope
  Covers four behaviours:
    1. All optional constraint combinations (none, proposed, excluded, both).
    2. Singleton proposal with SHA256-derived provisional cluster.
    3. Auto-generation of missing metadata (ere_request_id, timestamp).
    4. Duplicate publish under at-least-once semantics.

  These steps call EREPublishService with a mocked adapter.
  No real Redis connection is required for unit-level BDD scenarios.
"""

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from erspec.models.core import EntityMentionIdentifier
from erspec.models.ere import EntityMention, EntityMentionResolutionRequest
from pytest_bdd import given, parsers, scenario, then, when

from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from tests.conftest import TESTS_ROOT_DIR
from tests.feature.ere_contract_client.conftest import run_async

# ---------------------------------------------------------------------------
# Feature file path
# ---------------------------------------------------------------------------

FEATURE_FILE = str(
    TESTS_ROOT_DIR / "feature" / "ere_contract_client" / "request_publishing.feature"
)


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


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
    """Set up the EREPublishService with a mocked adapter."""
    adapter = MagicMock()
    adapter.push_request = AsyncMock(return_value=None)
    adapter.ping = AsyncMock(return_value=True)
    ctx["adapter"] = adapter
    ctx["service"] = EREPublishService(adapter)


@given("the messaging channel is reachable")
def messaging_channel_reachable(ctx):
    """Confirm the mock adapter simulates a reachable channel."""
    ctx["adapter"].push_request = AsyncMock(return_value=None)


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        "a valid entity mention with correlation triad "
        '("{source_id}", "{request_id}", "Organization")'
    )
)
def valid_entity_mention(ctx, source_id, request_id):
    """Build a valid EntityMentionResolutionRequest with the given triad."""
    ctx["request"] = EntityMentionResolutionRequest(
        ere_request_id="placeholder",
        entity_mention=EntityMention(
            identifiedBy=EntityMentionIdentifier(
                source_id=source_id,
                request_id=request_id,
                entity_type="Organization",
            ),
            content="some content",
            content_type="text/plain",
        ),
    )


@given(
    parsers.parse(
        'the request includes proposed placements "{proposed}" and excluded clusters "{excluded}"'
    )
)
def request_with_optional_fields(ctx, proposed, excluded):
    """Configure proposed placements and excluded clusters on the request."""
    request: EntityMentionResolutionRequest = ctx["request"]
    request.proposed_cluster_ids = (
        [] if proposed == "none" else [p.strip() for p in proposed.split(",")]
    )
    request.excluded_cluster_ids = (
        [] if excluded == "none" else [e.strip() for e in excluded.split(",")]
    )


@given(
    "the request includes a single proposed placement using the SHA256-derived provisional cluster"
)
def request_with_singleton_proposal(ctx):
    """Configure the request with a single proposed placement equal to the provisional cluster ID."""
    request: EntityMentionResolutionRequest = ctx["request"]
    identifier = request.entity_mention.identifiedBy
    raw = f"{identifier.source_id}:{identifier.request_id}:{identifier.entity_type}"
    provisional_id = "provisional:" + hashlib.sha256(raw.encode()).hexdigest()
    request.proposed_cluster_ids = [provisional_id]
    ctx["provisional_id"] = provisional_id


@given(parsers.parse('the resolution request has "{field}" not set'))
def request_field_not_set(ctx, field):
    """Configure the request to have the specified field treated as absent.

    Since erspec Pydantic models require ere_request_id at construction time,
    we use an empty string as the 'not set' sentinel; the service replaces
    any falsy ere_request_id with a generated UUID.
    """
    request: EntityMentionResolutionRequest = ctx["request"]
    if field == "ere_request_id":
        request.ere_request_id = ""
    elif field == "timestamp":
        request.timestamp = None
    ctx["unset_field"] = field


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the resolution request is published")
def publish_request(ctx):
    """Call EREPublishService.publish_request and store the result."""
    result = run_async(ctx["service"].publish_request(ctx["request"]))
    ctx["publish_count"] = ctx.get("publish_count", 0) + 1
    ctx["ere_request_id"] = result
    ctx["raised_exception"] = None


@when("the same resolution request is published again")
def publish_request_again(ctx):
    """Call EREPublishService.publish_request with the same request a second time."""
    result = run_async(ctx["service"].publish_request(ctx["request"]))
    ctx["publish_count"] = ctx.get("publish_count", 0) + 1
    ctx["ere_request_id_2"] = result
    ctx["raised_exception"] = None


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the request is enqueued on the messaging channel")
def request_enqueued(ctx):
    """Assert the adapter's push_request was called at least once."""
    ctx["adapter"].push_request.assert_called()


@then("the published request contains the complete correlation triad")
def published_request_has_triad(ctx):
    """Inspect the request passed to push_request and verify triad fields."""
    call_args = ctx["adapter"].push_request.call_args
    published: EntityMentionResolutionRequest = call_args[0][0]
    assert published.entity_mention.identifiedBy.source_id
    assert published.entity_mention.identifiedBy.request_id
    assert published.entity_mention.identifiedBy.entity_type


@then("the ere_request_id is present in the published request")
def ere_request_id_present(ctx):
    """Assert that the returned ere_request_id is non-empty."""
    assert ctx["ere_request_id"]


@then("the proposed placements contain exactly the provisional cluster identifier")
def proposed_contains_provisional(ctx):
    """Assert the published request carries exactly the provisional cluster ID."""
    call_args = ctx["adapter"].push_request.call_args
    published: EntityMentionResolutionRequest = call_args[0][0]
    assert len(published.proposed_cluster_ids) == 1
    assert published.proposed_cluster_ids[0] == ctx["provisional_id"]


@then(parsers.parse('the published request has "{field}" auto-populated'))
def field_auto_populated(ctx, field):
    """Assert the specified field was auto-generated by the service."""
    call_args = ctx["adapter"].push_request.call_args
    published: EntityMentionResolutionRequest = call_args[0][0]
    if field == "ere_request_id":
        assert published.ere_request_id
    elif field == "timestamp":
        assert published.timestamp is not None


@then("both requests are enqueued on the messaging channel")
def both_requests_enqueued(ctx):
    """Assert the adapter was called exactly twice (at-least-once allows duplicates)."""
    assert ctx["adapter"].push_request.call_count == 2
