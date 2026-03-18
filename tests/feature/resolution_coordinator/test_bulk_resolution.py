"""
Step definitions for: bulk_resolution.feature

Feature: Resolve a Bulk Resolution Request
  Covers two behaviours:
    1. Unpack multi-mention request, forward each to ERE, collect results
       (canonical, provisional, or error) within time budget.
    2. Each mention resolves independently regardless of others.

  These steps call ResolutionCoordinatorService.resolve_bulk with mocked dependencies.
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
    / "bulk_resolution.feature"
)


@scenario(FEATURE_FILE, "Unpack and resolve each mention independently")
def test_bulk_resolve_varying_outcomes():
    pass


@scenario(FEATURE_FILE, "Each mention resolves independently regardless of others")
def test_independent_resolution():
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
    TODO: Same setup as single_mention_resolution.
    """
    ctx["service"] = None  # TODO: build real ResolutionCoordinatorService


@given("the ERE execution window is configured")
def ere_execution_window_configured(ctx):
    """
    TODO: CoordinatorConfig with ere_execution_window_seconds set.
    """
    pass


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(parsers.parse("a bulk resolve request containing {mention_count:d} entity mentions"))
def bulk_request_with_n_mentions(ctx, mention_count):
    """
    TODO: Build list of EntityMention objects.
    """
    ctx["mention_count"] = mention_count
    ctx["mentions"] = [MagicMock() for _ in range(mention_count)]


@given(parsers.parse("{count:d} of those do not receive an ERE response in time"))
def n_mentions_timeout(ctx, count):
    """
    TODO: Configure waiter mock to timeout for count mentions.
    """
    ctx["timeout_count"] = count


@given(parsers.parse("{count:d} of those have malformed RDF content"))
def n_mentions_malformed(ctx, count):
    """
    TODO: Configure parser mock to fail on count mentions.
    """
    ctx["error_count"] = count


@given(parsers.parse('the {position} mention "{condition}"'))
def mention_at_position_has_condition(ctx, position, condition):
    """
    Configure the mock for a specific mention by position.

    TODO:
      idx = int(position) - 1  # "1" -> index 0
      if "receives an ERE response" in condition:
          configure waiter to fire for mentions[idx]
      elif "malformed RDF" in condition:
          configure parser to fail for mentions[idx]
      elif "does not receive an ERE response" in condition:
          configure waiter to timeout for mentions[idx]
    """
    ctx.setdefault("position_conditions", {})[position] = condition


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the bulk resolution request is submitted")
def submit_bulk(ctx):
    """
    TODO: ctx["results"] = await service.resolve_bulk(ctx["mentions"])
    """
    ctx["results"] = []  # TODO: replace with real service call
    ctx["raised_exception"] = None


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.parse("{count:d} results are returned in the same order as the input"))
def n_results_in_order(ctx, count):
    """
    TODO: assert len(ctx["results"]) == count
    """
    assert True  # TODO: implement


@then(parsers.parse("{count:d} of those results are errors"))
def n_results_are_errors(ctx, count):
    """
    TODO: errors = [r for r in ctx["results"] if isinstance(r, CoordinatorError)]
          assert len(errors) == count
    """
    assert True  # TODO: implement


@then(parsers.parse('the {position} mention returns "{result_type}"'))
def mention_at_position_returns(ctx, position, result_type):
    """
    Assert the result for a specific mention by position.

    TODO:
      idx = int(position) - 1
      if result_type == "canonical cluster identifier":
          assert isinstance(ctx["results"][idx], ResolutionDecisionRecord)
          assert not is_provisional(ctx["results"][idx])
      elif result_type == "parsing failure error":
          assert isinstance(ctx["results"][idx], ParsingFailedError)
      elif result_type == "provisional singleton identifier":
          assert isinstance(ctx["results"][idx], ResolutionDecisionRecord)
          assert is_provisional(ctx["results"][idx])
    """
    assert True  # TODO: implement
