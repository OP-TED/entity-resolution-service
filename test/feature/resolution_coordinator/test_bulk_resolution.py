"""
Step definitions for: bulk_resolution.feature

Feature: Resolve a Bulk Resolution Request
  Covers two behaviours:
    1. Unpack multi-mention request, collect results (canonical, provisional, or error).
    2. Each mention resolves independently regardless of others.

  Steps call ResolutionCoordinatorService.resolve_bulk with mocked dependencies
  and a real AsyncResolutionWaiter.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, create_autospec, patch

import pytest
from erspec.models.core import (
    ClusterReference,
    Decision,
    EntityMention,
    EntityMentionIdentifier,
)
from pytest_bdd import given, parsers, scenario, then, when

from ers.commons.adapters.provisional_id import derive_provisional_cluster_id
from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from ers.rdf_mention_parser.domain.exceptions import MalformedRDFError
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_coordinator.domain.exceptions import ParsingFailedError
from ers.resolution_coordinator.services.async_resolution_waiter import AsyncResolutionWaiter
from ers.resolution_coordinator.services.resolution_coordinator_service import (
    ResolutionCoordinatorService,
)
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE_FILE = str(
    Path(__file__).parent.parent.parent
    / "feature"
    / "resolution_coordinator"
    / "bulk_resolution.feature"
)

_FAST_CONFIG = type("C", (), {
    "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET": 0.1,
    "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET": 5.0,
})()
_CONFIG_PATH = "ers.resolution_coordinator.services.resolution_coordinator_service.config"


@scenario(FEATURE_FILE, "Unpack and resolve each mention independently")
def test_bulk_resolve_varying_outcomes():
    pass


@scenario(FEATURE_FILE, "Each mention resolves independently regardless of others")
def test_independent_resolution():
    pass


# ---------------------------------------------------------------------------
# Shared context + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    registry_svc = create_autospec(RequestRegistryService, instance=True)
    publish_svc = create_autospec(EREPublishService, instance=True)
    decision_svc = create_autospec(DecisionStoreService, instance=True)
    waiter = AsyncResolutionWaiter()
    with patch(_CONFIG_PATH, _FAST_CONFIG):
        service = ResolutionCoordinatorService(
            registry_service=registry_svc,
            ere_publish_service=publish_svc,
            decision_store_service=decision_svc,
            waiter=waiter,
        )
    return {
        "registry_svc": registry_svc,
        "publish_svc": publish_svc,
        "decision_svc": decision_svc,
        "waiter": waiter,
        "service": service,
        "mentions": [],
        "mention_configs": {},   # position (1-based str) → config dict
        "results": [],
        "raised_exception": None,
    }


def _make_mention(source: str, req: str) -> EntityMention:
    ident = EntityMentionIdentifier(source_id=source, request_id=req, entity_type="Organization")
    return EntityMention(
        identifiedBy=ident,
        content="<rdf/>",
        content_type="application/rdf+xml",
    )


def _make_decision(identifier: EntityMentionIdentifier, cluster_id: str) -> Decision:
    now = datetime.now(UTC)
    cluster = ClusterReference(cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85)
    return Decision(
        id="hash",
        about_entity_mention=identifier,
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
    pass  # Built in ctx fixture.


@given("the ERE execution window is configured")
def ere_execution_window_configured(ctx):
    pass  # Fast config applied at service construction.


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(parsers.parse("a bulk resolve request containing {mention_count:d} entity mentions"))
def bulk_request_with_n_mentions(ctx, mention_count):
    ctx["mentions"] = [
        _make_mention("BULK_SYS", f"req-bulk-{i:03d}")
        for i in range(mention_count)
    ]

    # Default mock behaviour: no pre-existing decision, ERE times out → provisional.
    def _per_call_side_effect(identifier):
        prov_id = derive_provisional_cluster_id(identifier)
        return _make_decision(identifier, cluster_id=prov_id)

    ctx["decision_svc"].get_decision_by_triad = AsyncMock(return_value=None)
    ctx["decision_svc"].store_decision = AsyncMock(
        side_effect=lambda **kw: _per_call_side_effect(kw["identifier"])
    )


@given(parsers.parse("{count:d} of those do not receive an ERE response in time"))
def n_mentions_timeout(ctx, count):
    ctx["timeout_count"] = count
    # No notification → timeout → provisional path is already default.


@given(parsers.parse("{count:d} of those have malformed RDF content"))
def n_mentions_malformed(ctx, count):
    ctx["error_count"] = count
    mentions = ctx["mentions"]
    # Last `count` mentions will raise a parsing error.
    error_indices = set(range(len(mentions) - count, len(mentions)))

    call_counter = {"n": 0}

    async def _register_side_effect(mention):
        idx = call_counter["n"]
        call_counter["n"] += 1
        if idx in error_indices:
            raise MalformedRDFError("bad rdf")

    ctx["registry_svc"].register_resolution_request = AsyncMock(
        side_effect=_register_side_effect
    )


@given(parsers.parse('the {position} mention "{condition}"'))
def mention_at_position_has_condition(ctx, position, condition):
    ctx["mention_configs"][position] = condition


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the bulk resolution request is submitted")
def submit_bulk(ctx):
    mentions = ctx["mentions"]
    waiter = ctx["waiter"]
    mention_configs = ctx["mention_configs"]

    # Build per-mention mock side effects for the position-based scenario.
    if mention_configs:
        _configure_per_position(ctx, mentions, mention_configs)

    async def _run():
        notification_tasks = []
        for i, mention in enumerate(mentions):
            position = str(i + 1)
            cfg = mention_configs.get(position, "")
            if "receives an ERE response" in cfg:
                key = (
                    f"{mention.identifiedBy.source_id}"
                    f"{mention.identifiedBy.request_id}"
                    f"{mention.identifiedBy.entity_type}"
                )

                async def _notify(k=key):
                    await asyncio.sleep(0.02)
                    await waiter.notify(k)

                notification_tasks.append(asyncio.create_task(_notify()))
        try:
            return await ctx["service"].resolve_bulk(mentions)
        finally:
            for t in notification_tasks:
                t.cancel()

    try:
        with patch(_CONFIG_PATH, _FAST_CONFIG):
            ctx["results"] = asyncio.run(_run())
        ctx["raised_exception"] = None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ctx["results"] = []
        ctx["raised_exception"] = exc


def _configure_per_position(ctx, mentions, mention_configs):
    """Wire identity-aware mocks per mention position for independent resolution scenario."""
    decision_svc = ctx["decision_svc"]
    registry_svc = ctx["registry_svc"]

    # Build maps keyed by (source_id, request_id) for identity-aware dispatch.
    canonical_decisions: dict[tuple, Decision] = {}
    malformed_ids: set[tuple] = set()

    for i, mention in enumerate(mentions):
        position = str(i + 1)
        cfg = mention_configs.get(position, "")
        ident = mention.identifiedBy
        key = (ident.source_id, ident.request_id)

        if "receives an ERE response" in cfg:
            canonical_decisions[key] = _make_decision(ident, cluster_id=f"cl-canonical-{i}")
        elif "malformed RDF" in cfg:
            malformed_ids.add(key)

    # Track how many times get_decision_by_triad has been called per identity.
    get_call_counts: dict[tuple, int] = {}

    async def _get_side_effect(identifier):
        key = (identifier.source_id, identifier.request_id)
        count = get_call_counts.get(key, 0)
        get_call_counts[key] = count + 1
        if key in canonical_decisions and count >= 1:
            # Second call (after ERE responded) → return canonical decision.
            return canonical_decisions[key]
        return None

    async def _store_side_effect(**kw):
        ident = kw["identifier"]
        return _make_decision(ident, cluster_id=derive_provisional_cluster_id(ident))

    async def _register_side_effect(mention):
        key = (mention.identifiedBy.source_id, mention.identifiedBy.request_id)
        if key in malformed_ids:
            raise MalformedRDFError("bad rdf")

    decision_svc.get_decision_by_triad = AsyncMock(side_effect=_get_side_effect)
    decision_svc.store_decision = AsyncMock(side_effect=_store_side_effect)
    registry_svc.register_resolution_request = AsyncMock(side_effect=_register_side_effect)


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.parse("{count:d} results are returned in the same order as the input"))
def n_results_in_order(ctx, count):
    assert ctx["raised_exception"] is None, f"Unexpected exception: {ctx['raised_exception']}"
    assert len(ctx["results"]) == count, (
        f"Expected {count} results, got {len(ctx['results'])}"
    )


@then(parsers.parse("{count:d} of those results are errors"))
def n_results_are_errors(ctx, count):
    errors = [r for r in ctx["results"] if isinstance(r, Exception)]
    assert len(errors) == count, (
        f"Expected {count} error results, got {len(errors)}: {errors}"
    )


@then(parsers.parse('the {position} mention returns "{result_type}"'))
def mention_at_position_returns(ctx, position, result_type):
    idx = int(position) - 1
    result = ctx["results"][idx]
    if result_type == "canonical cluster identifier":
        assert isinstance(result, tuple), f"Expected (Decision, outcome) at index {idx}, got {type(result)}"
        _, outcome = result
        assert outcome == ResolutionOutcome.CANONICAL, (
            f"Expected CANONICAL at index {idx}, got: {outcome}"
        )
    elif result_type == "parsing failure error":
        assert isinstance(result, ParsingFailedError), (
            f"Expected ParsingFailedError at index {idx}, got {type(result).__name__}"
        )
    elif result_type == "provisional singleton identifier":
        assert isinstance(result, tuple), f"Expected (Decision, outcome) at index {idx}, got {type(result)}"
        _, outcome = result
        assert outcome == ResolutionOutcome.PROVISIONAL, (
            f"Expected PROVISIONAL at index {idx}, got: {outcome}"
        )
    else:
        raise ValueError(f"Unknown result_type: {result_type!r}")
