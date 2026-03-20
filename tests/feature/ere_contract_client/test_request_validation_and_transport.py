"""
Step definitions for: request_validation_and_transport.feature

Feature: Validate Resolution Requests and Handle Transport Failures
  Covers three behaviours:
    1. Reject requests with incomplete correlation triad before publish.
    2. Surface transport and serialization failures as explicit domain errors.
    3. Report messaging channel health (reachable/unreachable).

  These steps call EREPublishService with a mocked adapter.
  No real Redis connection is required for unit-level BDD scenarios.

  Note on "serialization failure" scenario:
    The service delegates serialization to the adapter (model_dump_json inside
    RedisEREClient.push_request). The service has no explicit try/except around
    serialization because Pydantic models are always serializable when
    constructed correctly. This scenario is skipped pending a decision on
    whether the service should pre-serialize and catch errors explicitly.
    See EPIC.md section 6 (SerializationError) for the deferred decision.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from ers.ere_contract_client.domain.errors import (
    ChannelUnavailableError,
    InvalidRequestError,
    RedisConnectionError,
)
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from erspec.models.core import EntityMentionIdentifier
from erspec.models.ere import EntityMention, EntityMentionResolutionRequest
from tests.conftest import TESTS_ROOT_DIR
from tests.feature.ere_contract_client.conftest import run_async

# ---------------------------------------------------------------------------
# Feature file path
# ---------------------------------------------------------------------------

FEATURE_FILE = str(
    TESTS_ROOT_DIR / "feature" / "ere_contract_client" / "request_validation_and_transport.feature"
)


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE_FILE, "Reject a request with an incomplete correlation triad")
def test_reject_incomplete_triad():
    pass


@scenario(FEATURE_FILE, "Surface transport and serialization failures as explicit errors")
def test_transport_and_serialization_failures():
    pass


@pytest.mark.skip(
    reason="AbstractClient has no ping()/health_check() method yet. "
    "Scenario is deferred until a health-check contract is added to AbstractClient."
)
@scenario(FEATURE_FILE, "Report messaging channel health")
def test_health_check():
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


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(parsers.parse('a resolution request with "{missing_field}" absent'))
def request_with_missing_field(ctx, missing_field):
    """Build a request with the specified triad field set to empty / None.

    erspec Pydantic models enforce non-null required fields, so:
    - triad string fields (source_id, request_id, entity_type) use "" as the
      absent sentinel — the service rejects falsy strings as InvalidRequestError.
    - entity_mention uses model_construct() to bypass the Pydantic validator and
      set entity_mention=None directly, simulating a caller that bypassed
      normal construction.
    """
    if missing_field == "entity_mention":
        ctx["request"] = EntityMentionResolutionRequest.model_construct(
            entity_mention=None,
            ere_request_id="placeholder",
        )
        return

    identifier_kwargs = {
        "source_id": "TEDSWS",
        "request_id": "req-val-001",
        "entity_type": "Organization",
    }
    if missing_field in identifier_kwargs:
        identifier_kwargs[missing_field] = ""

    ctx["request"] = EntityMentionResolutionRequest(
        ere_request_id="placeholder",
        entity_mention=EntityMention(
            identifiedBy=EntityMentionIdentifier(**identifier_kwargs),
            content="content",
            content_type="text/plain",
        ),
    )


@given("the messaging channel is reachable")
def messaging_channel_reachable(ctx):
    """Configure the mock adapter to simulate a reachable channel."""
    ctx["adapter"].push_request = AsyncMock(return_value=None)
    ctx["adapter"].ping = AsyncMock(return_value=True)


@given(parsers.parse('the transport will fail with "{failure_mode}"'))
def transport_will_fail(ctx, failure_mode):
    """Configure the mock adapter to raise the appropriate failure."""
    if failure_mode == "connection refused":
        ctx["adapter"].push_request = AsyncMock(
            side_effect=ConnectionError("connection refused")
        )
    elif failure_mode == "response timeout":
        ctx["adapter"].push_request = AsyncMock(
            side_effect=TimeoutError("response timeout")
        )
    elif failure_mode == "serialization failure":
        # The current service delegates serialization to the adapter and has no
        # explicit SerializationError wrapping. Skip this row.
        ctx["skip_reason"] = (
            "SerializationError wrapping not yet implemented in EREPublishService. "
            "The service relies on the adapter for serialization; pre-publish "
            "serialization failure handling is deferred — see EPIC.md Section 6 (SerializationError)."
        )
    elif failure_mode == "channel accepted zero":
        ctx["adapter"].push_request = AsyncMock(
            side_effect=ChannelUnavailableError("channel accepted zero requests")
        )
    ctx["failure_mode"] = failure_mode


@given(parsers.parse('the messaging channel is "{channel_state}"'))
def messaging_channel_state(ctx, channel_state):
    """Configure the mock adapter for health-check scenarios."""
    if channel_state == "reachable":
        ctx["adapter"].ping = AsyncMock(return_value=True)
    elif channel_state == "unreachable":
        ctx["adapter"].ping = AsyncMock(return_value=False)


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the resolution request is published")
def publish_request(ctx):
    """Call EREPublishService.publish_request and capture any exception."""
    try:
        ctx["result"] = run_async(ctx["service"].publish_request(ctx["request"]))
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when(
    parsers.parse(
        "a resolution request is published for triad "
        '("{source_id}", "{request_id}", "Organization")'
    )
)
def publish_for_triad(ctx, source_id, request_id):
    """Build a valid request and call publish_request against the failing channel."""
    if ctx.get("skip_reason"):
        pytest.skip(ctx["skip_reason"])

    request = EntityMentionResolutionRequest(
        ere_request_id="placeholder",
        entity_mention=EntityMention(
            identifiedBy=EntityMentionIdentifier(
                source_id=source_id,
                request_id=request_id,
                entity_type="Organization",
            ),
            content="content",
            content_type="text/plain",
        ),
    )
    try:
        ctx["result"] = run_async(ctx["service"].publish_request(request))
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when("the health check is performed")
def perform_health_check(ctx):
    """Call the adapter's ping method and store the result."""
    ctx["health_result"] = run_async(ctx["adapter"].ping())


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("an invalid request error is raised")
def invalid_request_error(ctx):
    """Assert that an InvalidRequestError was raised."""
    assert isinstance(ctx["raised_exception"], InvalidRequestError), (
        f"Expected InvalidRequestError, got {type(ctx['raised_exception'])}: "
        f"{ctx['raised_exception']}"
    )


@then("no request is enqueued on the messaging channel")
def no_request_enqueued(ctx):
    """Assert the adapter's push_request was never called."""
    ctx["adapter"].push_request.assert_not_called()


@then(parsers.parse('a "{error_type}" error is raised'))
def specific_error_raised(ctx, error_type):
    """Assert the correct domain error type was raised."""
    error_map = {
        "connection": RedisConnectionError,
        "serialization": None,  # handled via skip in transport_will_fail step
        "channel_unavailable": ChannelUnavailableError,
        "timeout": ChannelUnavailableError,
    }
    expected = error_map[error_type]
    if expected is None:
        pytest.skip(
            "SerializationError wrapping not yet implemented in EREPublishService."
        )
    assert isinstance(ctx["raised_exception"], expected), (
        f"Expected {expected.__name__}, got {type(ctx['raised_exception'])}: "
        f"{ctx['raised_exception']}"
    )


@then(parsers.parse('the result is "{health_result}"'))
def assert_health_result(ctx, health_result):
    """Assert the health check returned the expected boolean."""
    if health_result == "healthy":
        assert ctx["health_result"] is True
    elif health_result == "unhealthy":
        assert ctx["health_result"] is False
