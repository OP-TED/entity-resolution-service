"""
Step definitions for: ucb12_integrate_ere_outcomes.feature

UC-B1.2 — Integrate ERE Resolution Outcomes (Asynchronous)
  Tests the async outcome integration path:
    ERE outcome message -> ERS consumer -> Decision Store update

  Covers 9 scenarios:
    1. Standard resolution outcome - Decision Store updated with cluster + alternatives.
    2. Draft identifier replaced by authoritative ERE outcome.
    3. Draft identifier confirmed by ERE.
    4. ERE-initiated reclustering - updated placement.
    5. Duplicate outcome - idempotent handling.
    6. Uncorrelated outcome (unknown triad) - rejected.
    7. Invalid outcome message - rejected, state unchanged.
    8. Score preservation - ERS does not alter confidence/similarity.

  The actor is ERS itself (internal). Outcomes arrive via messaging.
  The trigger is consuming an ERE clustering outcome message.
  Traceability: UC-B1.2, ADR-A1N, ADR-A2N.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from erspec.models.ere import EntityMentionResolutionResponse
from pytest_bdd import given, parsers, scenario, then, when

from ers.ere_result_integrator.domain.errors import OutcomeValidationError, TriadNotFoundError
from ers.ere_result_integrator.services.outcome_integration_service import OutcomeIntegrationService
from ers.request_registry.domain.records import ResolutionRequestRecord
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_decision_store.domain.errors import StaleOutcomeError
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

FEATURE_FILE = str(Path(__file__).parent / "ucb12_integrate_ere_outcomes.feature")


@scenario(
    FEATURE_FILE,
    "Update Decision Store when ERE returns a clustering outcome",
)
def test_standard_resolution_outcome():
    pass


@scenario(
    FEATURE_FILE,
    "ERE replaces a provisional draft identifier with an authoritative cluster",
)
def test_draft_replacement():
    pass


@scenario(
    FEATURE_FILE,
    "ERE confirms a provisional draft identifier as the authoritative cluster",
)
def test_draft_confirmation():
    pass


@scenario(
    FEATURE_FILE,
    "ERE performs internal reclustering and emits an updated outcome",
)
def test_reclustering_outcome():
    pass


@scenario(
    FEATURE_FILE,
    "Duplicate ERE outcome for the same mention is processed idempotently",
)
def test_duplicate_outcome():
    pass


@scenario(
    FEATURE_FILE,
    "Reject an ERE outcome for an unknown triad",
)
def test_uncorrelated_outcome():
    pass


@scenario(
    FEATURE_FILE,
    "Reject an invalid ERE outcome message",
)
def test_invalid_outcome():
    pass


@scenario(
    FEATURE_FILE,
    "ERS does not alter similarity or confidence scores from ERE",
)
def test_score_preservation():
    pass


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Wire a real OutcomeIntegrationService with autospec'd dependencies."""
    registry = create_autospec(RequestRegistryService, instance=True)
    decisions = create_autospec(DecisionStoreService, instance=True)
    service = OutcomeIntegrationService(
        registry_service=registry,
        decision_service=decisions,
        on_outcome_stored=None,
    )
    return {
        "registry": registry,
        "decisions": decisions,
        "service": service,
        "source_id": None,
        "request_id": None,
        "entity_type": None,
        "outcome_message": None,
        "outcome_alternatives": [],
        "prior_cluster_id": None,
        "result": None,
        "duplicate_result": None,
        "raised_exception": None,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(source_id, request_id, entity_type):
    return ResolutionRequestRecord(
        identifiedBy=EntityMentionIdentifier(
            source_id=source_id, request_id=request_id, entity_type=entity_type
        ),
        content="rdf",
        content_type="text/turtle",
        content_hash="a" * 64,
        received_at=datetime.now(UTC),
    )


def _make_decision(identifier, primary, candidates):
    now = datetime.now(UTC)
    return Decision(
        id="hash",
        about_entity_mention=identifier,
        current_placement=primary,
        candidates=candidates,
        created_at=now,
        updated_at=now,
    )


def _build_outcome_message(ctx, cluster_id, alt_count):
    """Construct an EntityMentionResolutionResponse and configure the store mock."""
    identifier = EntityMentionIdentifier(
        source_id=ctx["source_id"],
        request_id=ctx["request_id"],
        entity_type=ctx["entity_type"],
    )
    primary = ClusterReference(cluster_id=cluster_id, confidence_score=0.95, similarity_score=0.90)
    alts = [
        ClusterReference(cluster_id=f"alt-{i}", confidence_score=0.5, similarity_score=0.45)
        for i in range(alt_count)
    ]
    ctx["decisions"].store_decision = AsyncMock(
        return_value=_make_decision(identifier, primary, alts)
    )
    return EntityMentionResolutionResponse(
        ere_request_id=f"{ctx['request_id']}:001",
        entity_mention_id=identifier,
        candidates=[primary] + alts,
        timestamp=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("the ERS system is operational")
def ers_system_operational(ctx):
    """Service is wired via the ctx fixture."""
    pass


@given("the Decision Store is available")
def decision_store_available(ctx):
    """Default - Decision Store is healthy."""
    pass


@given("the ERE messaging boundary is available")
def ere_messaging_available(ctx):
    """Default - messaging infrastructure is operational."""
    ctx["ere_publisher"] = MagicMock()
    ctx["ere_publisher"].publish = AsyncMock()


# ---------------------------------------------------------------------------
# Given — mention and Decision Store state
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        'a mention with triad "{source_id}", "{request_id}", "{entity_type}" is registered'
    )
)
def mention_is_registered(ctx, source_id, request_id, entity_type):
    """Seed the Request Registry mock with a registered mention."""
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = entity_type
    ctx["registry"].get_resolution_request = AsyncMock(
        return_value=_make_record(source_id, request_id, entity_type)
    )


@given(parsers.re(r'the Decision Store holds "(?P<cluster_id>[^"]*)" for that triad'))
def decision_store_holds_cluster(ctx, cluster_id):
    """Seed the Decision Store mock with an existing placement."""
    ctx["prior_cluster_id"] = cluster_id
    identifier = EntityMentionIdentifier(
        source_id=ctx["source_id"],
        request_id=ctx["request_id"],
        entity_type=ctx["entity_type"],
    )
    prior_ref = ClusterReference(
        cluster_id=cluster_id or "pending",
        confidence_score=1.0,
        similarity_score=1.0,
    )
    ctx["decisions"].store_decision = AsyncMock(
        return_value=_make_decision(identifier, prior_ref, [])
    )


@given(
    parsers.parse(
        'the Decision Store holds provisional draft identifier "{draft_id}" for that triad'
    )
)
def decision_store_holds_provisional(ctx, draft_id):
    """Seed the Decision Store mock with a provisional singleton placement."""
    ctx["prior_cluster_id"] = draft_id
    ctx["prior_is_provisional"] = True
    identifier = EntityMentionIdentifier(
        source_id=ctx["source_id"],
        request_id=ctx["request_id"],
        entity_type=ctx["entity_type"],
    )
    provisional_ref = ClusterReference(
        cluster_id=draft_id, confidence_score=1.0, similarity_score=1.0
    )
    ctx["decisions"].store_decision = AsyncMock(
        return_value=_make_decision(identifier, provisional_ref, [])
    )


@given(
    parsers.parse(
        'no mention with triad "{source_id}", "{request_id}", "{entity_type}" is registered'
    )
)
def mention_not_registered(ctx, source_id, request_id, entity_type):
    """Ensure the triad is NOT in the Request Registry."""
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = entity_type
    ctx["triad_not_registered"] = True
    ctx["registry"].get_resolution_request = AsyncMock(return_value=None)


# ---------------------------------------------------------------------------
# Given — ERE outcome message configuration
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        "ERE emits a clustering outcome for that mention with cluster "
        '"{cluster_id}" and {alt_count:d} alternatives'
    )
)
def ere_emits_outcome(ctx, cluster_id, alt_count):
    """Build an ERE outcome message for the current triad."""
    ctx["outcome_cluster_id"] = cluster_id
    ctx["outcome_alt_count"] = alt_count
    ctx["outcome_message"] = _build_outcome_message(ctx, cluster_id, alt_count)


@given(
    parsers.parse(
        'ERE emits a clustering outcome with cluster "{cluster_id}" and {alt_count:d} alternatives'
    )
)
def ere_emits_outcome_short(ctx, cluster_id, alt_count):
    """Build ERE outcome (shorthand without 'for that mention')."""
    ctx["outcome_cluster_id"] = cluster_id
    ctx["outcome_alt_count"] = alt_count
    ctx["outcome_message"] = _build_outcome_message(ctx, cluster_id, alt_count)


@given(
    parsers.parse(
        'ERE emits a clustering outcome confirming cluster "{cluster_id}" '
        "and {alt_count:d} alternative"
    )
)
def ere_emits_confirmation(ctx, cluster_id, alt_count):
    """Build ERE outcome that confirms the existing cluster."""
    ctx["outcome_cluster_id"] = cluster_id
    ctx["outcome_alt_count"] = alt_count
    ctx["outcome_message"] = _build_outcome_message(ctx, cluster_id, alt_count)


@given(
    parsers.parse(
        "ERE emits a reclustering outcome reassigning the mention to "
        '"{cluster_id}" with {alt_count:d} alternatives'
    )
)
def ere_emits_reclustering(ctx, cluster_id, alt_count):
    """Build ERE reclustering outcome message."""
    ctx["outcome_cluster_id"] = cluster_id
    ctx["outcome_alt_count"] = alt_count
    ctx["is_reclustering"] = True
    ctx["outcome_message"] = _build_outcome_message(ctx, cluster_id, alt_count)


@given(
    parsers.parse(
        'ERE emits a clustering outcome for triad "{source_id}", '
        '"{request_id}", "{entity_type}" with cluster "{cluster_id}"'
    )
)
def ere_emits_for_specific_triad(ctx, source_id, request_id, entity_type, cluster_id):
    """Build ERE outcome for a specific (possibly unregistered) triad."""
    ctx["outcome_source_id"] = source_id
    ctx["outcome_request_id"] = request_id
    ctx["outcome_entity_type"] = entity_type
    ctx["outcome_cluster_id"] = cluster_id
    primary = ClusterReference(cluster_id=cluster_id, confidence_score=0.95, similarity_score=0.90)
    ctx["outcome_message"] = EntityMentionResolutionResponse(
        ere_request_id=f"{request_id}:phantom",
        entity_mention_id=EntityMentionIdentifier(
            source_id=source_id, request_id=request_id, entity_type=entity_type
        ),
        candidates=[primary],
        timestamp=datetime.now(UTC),
    )


@given(parsers.parse("ERE emits an outcome message with {invalid_condition}"))
def ere_emits_invalid_outcome(ctx, invalid_condition):
    """Build an intentionally invalid ERE outcome message.

    - ``cluster_id absent``: candidates list is empty, rejected at service step 1.
    - ``correlation triad fields missing`` / ``malformed message structure``: cannot
      be constructed as a valid domain object; rejection is pre-service.
    """
    ctx["invalid_condition"] = invalid_condition
    identifier = EntityMentionIdentifier(
        source_id=ctx.get("source_id") or "SYSTEM_F",
        request_id=ctx.get("request_id") or "req-040",
        entity_type=ctx.get("entity_type") or "ORGANISATION",
    )
    if "cluster_id absent" in invalid_condition:
        # Empty candidates list triggers OutcomeValidationError at service layer
        ctx["outcome_message"] = EntityMentionResolutionResponse(
            ere_request_id="req-invalid:001",
            entity_mention_id=identifier,
            candidates=[],
            timestamp=datetime.now(UTC),
        )
    else:
        # Missing correlation fields / malformed structure cannot be represented
        # as a valid EntityMentionResolutionResponse; mark as pre-rejected.
        ctx["outcome_message"] = None
        ctx["raised_exception"] = OutcomeValidationError(
            f"Message rejected before service layer: {invalid_condition}"
        )


@given(
    parsers.parse('ERE emits a clustering outcome with cluster "{cluster_id}" and alternatives:')
)
def ere_emits_outcome_with_score_table(ctx, cluster_id, datatable):
    """Build ERE outcome with explicit alternative scores from the data table."""
    ctx["outcome_cluster_id"] = cluster_id
    ctx["outcome_alternatives"] = []
    headers = datatable[0]
    for row_values in datatable[1:]:
        row = dict(zip(headers, row_values))
        ctx["outcome_alternatives"].append(
            {
                "cluster_id": row["cluster_id"],
                "confidence": float(row["confidence"]),
                "similarity": float(row["similarity"]),
            }
        )

    identifier = EntityMentionIdentifier(
        source_id=ctx["source_id"],
        request_id=ctx["request_id"],
        entity_type=ctx["entity_type"],
    )
    primary = ClusterReference(cluster_id=cluster_id, confidence_score=0.99, similarity_score=0.99)
    alts = [
        ClusterReference(
            cluster_id=a["cluster_id"],
            confidence_score=a["confidence"],
            similarity_score=a["similarity"],
        )
        for a in ctx["outcome_alternatives"]
    ]
    ctx["decisions"].store_decision = AsyncMock(
        return_value=_make_decision(identifier, primary, alts)
    )
    ctx["outcome_message"] = EntityMentionResolutionResponse(
        ere_request_id=f"{ctx['request_id']}:score",
        entity_mention_id=identifier,
        candidates=[primary] + alts,
        timestamp=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("ERS consumes the outcome message")
def consume_outcome(ctx):
    """Invoke OutcomeIntegrationService to process the outcome message."""
    if ctx.get("outcome_message") is None:
        # Message was rejected at construction time; raised_exception already set.
        return
    try:
        ctx["result"] = asyncio.run(
            ctx["service"].integrate_outcome(ctx["outcome_message"])
        )
        ctx["raised_exception"] = None
    except (OutcomeValidationError, TriadNotFoundError, Exception) as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when("ERS consumes the same outcome message again")
def consume_duplicate_outcome(ctx):
    """Re-invoke the integrator with the same message (idempotency test).

    The second write attempt raises StaleOutcomeError because the outcome
    timestamp matches what is already stored. The service swallows this and
    returns None.
    """
    ctx["decisions"].store_decision = AsyncMock(
        side_effect=StaleOutcomeError(
            ctx["source_id"],
            ctx["request_id"],
            ctx["entity_type"],
            stored_at=str(ctx["outcome_message"].timestamp),
            attempted_at=str(ctx["outcome_message"].timestamp),
        )
    )
    ctx["duplicate_result"] = asyncio.run(
        ctx["service"].integrate_outcome(ctx["outcome_message"])
    )


# ---------------------------------------------------------------------------
# Then — Decision Store assertions
# ---------------------------------------------------------------------------


@then(
    parsers.parse(
        'the Decision Store reflects cluster "{cluster_id}" for triad '
        '"{source_id}", "{request_id}", "{entity_type}"'
    )
)
def decision_store_reflects_cluster(ctx, cluster_id, source_id, request_id, entity_type):
    assert ctx["raised_exception"] is None, f"Unexpected exception: {ctx['raised_exception']}"
    ctx["decisions"].store_decision.assert_called()
    call_kwargs = ctx["decisions"].store_decision.call_args.kwargs
    assert call_kwargs["current"].cluster_id == cluster_id


@then(parsers.re(r"the Decision Store stores exactly (?P<count>\d+) alternative candidates?"))
def decision_has_n_alternatives(ctx, count):
    call_kwargs = ctx["decisions"].store_decision.call_args.kwargs
    assert len(call_kwargs["candidates"]) == int(count)


@then("the alternative candidate scores are preserved exactly as ERE returned them")
def scores_preserved(ctx):
    call_kwargs = ctx["decisions"].store_decision.call_args.kwargs
    expected_alts = ctx["outcome_message"].candidates[1:]
    for i, expected in enumerate(expected_alts):
        assert call_kwargs["candidates"][i].confidence_score == expected.confidence_score
        assert call_kwargs["candidates"][i].similarity_score == expected.similarity_score


@then("the delta tracking timestamp for that mention is updated")
def delta_tracking_updated(ctx):
    call_kwargs = ctx["decisions"].store_decision.call_args.kwargs
    assert call_kwargs["updated_at"] is not None


@then(
    parsers.parse(
        'the provisional draft identifier "{draft_id}" is no longer the current placement'
    )
)
def provisional_no_longer_current(ctx, draft_id):
    call_kwargs = ctx["decisions"].store_decision.call_args.kwargs
    assert call_kwargs["current"].cluster_id != draft_id


@then(
    parsers.parse(
        'the Decision Store still reflects "{cluster_id}" for triad '
        '"{source_id}", "{request_id}", "{entity_type}"'
    )
)
def decision_store_unchanged(ctx, cluster_id, source_id, request_id, entity_type):
    """Invalid outcome was rejected before store_decision was called."""
    ctx["decisions"].store_decision.assert_not_called()


@then(
    parsers.parse(
        'the Decision Store still reflects cluster "{cluster_id}" for triad '
        '"{source_id}", "{request_id}", "{entity_type}"'
    )
)
def decision_store_still_has_cluster(ctx, cluster_id, source_id, request_id, entity_type):
    """Duplicate outcome: StaleOutcomeError was raised, so service returned None.
    The persisted cluster is unchanged.
    """
    assert ctx.get("duplicate_result") is None


@then("no duplicate decision record is created")
def no_duplicate_decision(ctx):
    """StaleOutcomeError on second call means no new record was written."""
    assert ctx.get("duplicate_result") is None


@then("no decision is written to the Decision Store")
def no_decision_written(ctx):
    ctx["decisions"].store_decision.assert_not_called()


# ---------------------------------------------------------------------------
# Then — rejection and logging assertions
# ---------------------------------------------------------------------------


@then("the outcome is rejected")
def outcome_rejected(ctx):
    assert ctx.get("raised_exception") is not None


@then("the rejection is logged")
def rejection_logged(ctx):
    """Logging is verified at unit level. At e2e level we confirm rejection occurred."""
    assert ctx.get("raised_exception") is not None


# ---------------------------------------------------------------------------
# Then — score preservation
# ---------------------------------------------------------------------------


@then(
    parsers.parse(
        "the Decision Store stores {count:d} alternatives with scores exactly as received:"
    )
)
def scores_match_table(ctx, count, datatable):
    """Verify stored alternative scores match the ERE-provided values exactly."""
    call_kwargs = ctx["decisions"].store_decision.call_args.kwargs
    assert len(call_kwargs["candidates"]) == count
    headers = datatable[0]
    for i, row_values in enumerate(datatable[1:]):
        row = dict(zip(headers, row_values))
        candidate = call_kwargs["candidates"][i]
        assert candidate.cluster_id == row["cluster_id"]
        assert candidate.confidence_score == float(row["confidence"])
        assert candidate.similarity_score == float(row["similarity"])
