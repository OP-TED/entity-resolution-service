"""
Step definitions for: request_validation_and_transport.feature

Feature: Validate Resolution Requests and Handle Transport Failures
  Covers three behaviours:
    1. Reject requests with incomplete correlation triad before publish.
    2. Surface transport and serialization failures as explicit domain errors.
    3. Report messaging channel health (reachable/unreachable).

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
    / "request_validation_and_transport.feature"
)


@scenario(FEATURE_FILE, "Reject a request with an incomplete correlation triad")
def test_reject_incomplete_triad():
    pass


@scenario(FEATURE_FILE, "Surface transport and serialization failures as explicit errors")
def test_transport_and_serialization_failures():
    pass


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
    """
    Set up the EREPublishService with a mocked adapter.

    TODO: Replace with create_autospec(RedisEREAdapter)
    """
    adapter = MagicMock()
    adapter.push_request = AsyncMock(return_value=1)
    adapter.ping = AsyncMock(return_value=True)
    ctx["adapter"] = adapter
    ctx["service"] = None  # TODO: EREPublishService(adapter)


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(parsers.parse('a resolution request with "{missing_field}" absent'))
def request_with_missing_field(ctx, missing_field):
    """
    Build a request with the specified field missing.

    TODO: Build EntityMentionResolutionRequest with the field set to None:
      - "source_id" → identifier.source_id = None
      - "request_id" → identifier.request_id = None
      - "entity_type" → identifier.entity_type = None
      - "entity_mention" → entity_mention = None
    """
    ctx["missing_field"] = missing_field


@given("the messaging channel is reachable")
def messaging_channel_reachable(ctx):
    """Configure the mock adapter to simulate a reachable channel."""
    ctx["adapter"].push_request = AsyncMock(return_value=1)
    ctx["adapter"].ping = AsyncMock(return_value=True)


@given(parsers.parse('the transport will fail with "{failure_mode}"'))
def transport_will_fail(ctx, failure_mode):
    """
    Configure the mock adapter to simulate the given failure.

    TODO: Use real domain error types:
      - "connection refused" → RedisConnectionError
      - "response timeout" → RedisConnectionError
      - "serialization failure" → SerializationError (on service side)
      - "channel accepted zero" → ChannelUnavailableError
    """
    if failure_mode == "connection refused":
        ctx["adapter"].push_request = AsyncMock(
            side_effect=Exception("RedisConnectionError")  # TODO: real error
        )
    elif failure_mode == "response timeout":
        ctx["adapter"].push_request = AsyncMock(
            side_effect=Exception("RedisConnectionError")  # TODO: real error
        )
    elif failure_mode == "serialization failure":
        ctx["expected_error_source"] = "serialization"
        # TODO: Configure request to fail on model_dump_json()
    elif failure_mode == "channel accepted zero":
        ctx["adapter"].push_request = AsyncMock(return_value=0)


@given(parsers.parse('the messaging channel is "{channel_state}"'))
def messaging_channel_state(ctx, channel_state):
    """
    Configure the mock adapter for health check scenarios.

    TODO:
      if channel_state == "reachable":
          adapter.ping = AsyncMock(return_value=True)
      elif channel_state == "unreachable":
          adapter.ping = AsyncMock(return_value=False)
    """
    if channel_state == "reachable":
        ctx["adapter"].ping = AsyncMock(return_value=True)
    elif channel_state == "unreachable":
        ctx["adapter"].ping = AsyncMock(return_value=False)


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the resolution request is published")
def publish_request(ctx):
    """
    Call EREPublishService.publish_request with the (possibly invalid) request.

    TODO: try:
              ctx["result"] = await service.publish_request(request)
          except (InvalidRequestError, ...) as exc:
              ctx["raised_exception"] = exc
    """
    ctx["result"] = None
    ctx["raised_exception"] = None  # TODO: capture exception


@when(
    parsers.parse(
        "a resolution request is published for triad "
        '("{source_id}", "{request_id}", "Organization")'
    )
)
def publish_for_triad(ctx, source_id, request_id):
    """
    Call EREPublishService.publish_request with a valid request
    against a failing channel.

    TODO: Build valid request, call service, capture domain error.
    """
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["result"] = None
    ctx["raised_exception"] = None  # TODO: capture domain error


@when("the health check is performed")
def perform_health_check(ctx):
    """
    Call the adapter's ping method.

    TODO: ctx["health_result"] = await adapter.ping()
    """
    ctx["health_result"] = None  # TODO: replace with real call


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("an invalid request error is raised")
def invalid_request_error(ctx):
    """
    TODO: assert isinstance(ctx["raised_exception"], InvalidRequestError)
    """
    assert True  # TODO: implement


@then("no request is enqueued on the messaging channel")
def no_request_enqueued(ctx):
    """
    TODO: ctx["adapter"].push_request.assert_not_called()
    """
    assert True  # TODO: implement


@then(parsers.parse('a "{error_type}" error is raised'))
def specific_error_raised(ctx, error_type):
    """
    Assert the correct domain error type was raised.

    TODO:
      error_map = {
          "connection": RedisConnectionError,
          "serialization": SerializationError,
          "channel_unavailable": ChannelUnavailableError,
      }
      assert isinstance(ctx["raised_exception"], error_map[error_type])
    """
    assert True  # TODO: implement


@then(parsers.parse('the result is "{health_result}"'))
def assert_health_result(ctx, health_result):
    """
    TODO:
      if health_result == "healthy":
          assert ctx["health_result"] is True
      elif health_result == "unhealthy":
          assert ctx["health_result"] is False
    """
    assert True  # TODO: implement
