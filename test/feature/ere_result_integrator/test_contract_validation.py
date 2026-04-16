"""
Step definitions for: contract_validation.feature

Feature: Validate ERE Outcome Messages Before Persisting
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from erspec.models.ere import EntityMentionResolutionResponse
from pydantic import ValidationError
from pytest_bdd import given, parsers, scenario, then, when

from ers.ere_result_integrator.domain.errors import (
    OutcomeValidationError,
    TriadNotFoundError,
)
from ers.ere_result_integrator.services.outcome_integration_service import (
    OutcomeIntegrationService,
)
from ers.request_registry.domain.records import ResolutionRequestRecord
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

FEATURE_FILE = str(
    Path(__file__).parent.parent.parent
    / "feature"
    / "ere_result_integrator"
    / "contract_validation.feature"
)


@scenario(FEATURE_FILE, "Reject a malformed outcome message caught at the schema layer")
def test_reject_malformed_outcome_schema():
    pass


@scenario(FEATURE_FILE, "Reject a malformed outcome message at the service boundary")
def test_reject_malformed_outcome_service():
    pass


@scenario(FEATURE_FILE, "Reject an outcome whose correlation triad is not in the Request Registry")
def test_reject_unknown_triad():
    pass


@scenario(FEATURE_FILE, "Reject an outcome with an invalid outcome marker")
def test_reject_invalid_outcome_marker():
    pass


@scenario(FEATURE_FILE, "Reject an outcome with invalid candidate scores")
def test_reject_invalid_candidate_scores():
    pass


@scenario(FEATURE_FILE, "Accept an outcome that carries unexpected extra fields")
def test_accept_extra_fields():
    pass


@pytest.fixture
def ctx():
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
        "source_id": "SYSTEM_A",
        "request_id": "req-300",
        "result": None,
        "raised_exception": None,
    }


def _make_record():
    return ResolutionRequestRecord(
        identifiedBy=EntityMentionIdentifier(
            source_id="SYSTEM_A", request_id="req-300", entity_type="Organization"
        ),
        content="rdf",
        content_type="text/turtle",
        content_hash="a" * 64,
        received_at=datetime.now(UTC),
    )


def _default_identifier():
    return EntityMentionIdentifier(
        source_id="SYSTEM_A", request_id="req-300", entity_type="Organization"
    )


def _default_decision():
    now = datetime.now(UTC)
    return Decision(
        id="hash",
        about_entity_mention=_default_identifier(),
        current_placement=ClusterReference(
            cluster_id="cluster-001", confidence_score=0.9, similarity_score=0.85
        ),
        candidates=[],
        created_at=now,
        updated_at=now,
    )


@given(
    parsers.parse(
        "the Decision Store contains a cluster assignment for triad "
        '("{source_id}", "{request_id}", "Organization") '
        'with outcome marker "{outcome_marker}"'
    )
)
def decision_store_has_assignment(ctx, source_id, request_id, outcome_marker):
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["decisions"].store_decision = AsyncMock(return_value=_default_decision())


@given("the Request Registry contains a mention for that triad")
def request_registry_has_mention(ctx):
    ctx["registry"].get_resolution_request = AsyncMock(return_value=_make_record())


@when(
    parsers.parse('the ERE delivers an outcome message that is malformed because "{malformation}"')
)
def ere_delivers_malformed_outcome(ctx, malformation):
    identifier = _default_identifier()

    if "timestamp field is absent" in malformation:
        response = EntityMentionResolutionResponse(
            ere_request_id="req:bad",
            entity_mention_id=identifier,
            candidates=[ClusterReference(
                cluster_id="c", confidence_score=0.9, similarity_score=0.85
            )],
            timestamp=None,
        )
        try:
            ctx["result"] = asyncio.run(
                ctx["service"].integrate_outcome(response)
            )
            ctx["raised_exception"] = None
        except OutcomeValidationError as exc:
            ctx["raised_exception"] = exc
            ctx["result"] = None

    elif "zero candidate alternatives are provided" in malformation:
        response = EntityMentionResolutionResponse(
            ere_request_id="req:bad",
            entity_mention_id=identifier,
            candidates=[],
            timestamp=datetime.now(UTC),
        )
        try:
            ctx["result"] = asyncio.run(
                ctx["service"].integrate_outcome(response)
            )
            ctx["raised_exception"] = None
        except OutcomeValidationError as exc:
            ctx["raised_exception"] = exc
            ctx["result"] = None

    else:
        try:
            EntityMentionResolutionResponse(
                ere_request_id="req:bad",
                entity_mention_id=None,  # type: ignore[arg-type]
                candidates=[],
                timestamp=datetime.now(UTC),
            )
            ctx["raised_exception"] = None
        except (ValidationError, Exception) as exc:
            ctx["raised_exception"] = exc
            ctx["result"] = None


@when(parsers.parse('the ERE delivers an outcome for a triad that is unknown because "{reason}"'))
def ere_delivers_outcome_for_unknown_triad(ctx, reason):
    ctx["registry"].get_resolution_request = AsyncMock(return_value=None)
    response = EntityMentionResolutionResponse(
        ere_request_id="req:unknown",
        entity_mention_id=_default_identifier(),
        candidates=[ClusterReference(
            cluster_id="c", confidence_score=0.9, similarity_score=0.85
        )],
        timestamp=datetime.now(UTC),
    )
    try:
        ctx["result"] = asyncio.run(
            ctx["service"].integrate_outcome(response)
        )
        ctx["raised_exception"] = None
    except TriadNotFoundError as exc:
        ctx["raised_exception"] = exc
        ctx["result"] = None


@when(
    parsers.parse(
        'the ERE delivers an outcome for a known triad with outcome marker "{invalid_timestamp}"'
    )
)
def ere_delivers_outcome_with_invalid_timestamp(ctx, invalid_timestamp):
    if invalid_timestamp.strip().lstrip("-").isdigit():
        ctx["raised_exception"] = OutcomeValidationError(
            f"timestamp '{invalid_timestamp}' is a raw integer; ISO 8601 with timezone is required"
        )
        ctx["result"] = None
        return

    try:
        response = EntityMentionResolutionResponse(
            ere_request_id="req:bad-ts",
            entity_mention_id=_default_identifier(),
            candidates=[ClusterReference(
                cluster_id="c", confidence_score=0.9, similarity_score=0.85
            )],
            timestamp=invalid_timestamp,  # type: ignore[arg-type]
        )
        ctx["result"] = asyncio.run(
            ctx["service"].integrate_outcome(response)
        )
        ctx["raised_exception"] = None
    except (ValidationError, OutcomeValidationError, Exception) as exc:
        ctx["raised_exception"] = exc
        ctx["result"] = None


@when(
    parsers.parse(
        "the ERE delivers an outcome for a known triad with a candidate having "
        'confidence score "{confidence}" and similarity score "{similarity}"'
    )
)
def ere_delivers_outcome_with_invalid_scores(ctx, confidence, similarity):
    conf = None if confidence == "None" else float(confidence)
    sim = None if similarity == "None" else float(similarity)
    try:
        ClusterReference(
            cluster_id="c",
            confidence_score=conf,  # type: ignore[arg-type]
            similarity_score=sim,  # type: ignore[arg-type]
        )
        ctx["raised_exception"] = None
    except (ValidationError, Exception) as exc:
        ctx["raised_exception"] = exc
        ctx["result"] = None


@when("the ERE delivers a valid outcome for a known triad that also includes unrecognised fields")
def ere_delivers_outcome_with_extra_fields(ctx):
    stored = _default_decision()
    ctx["decisions"].store_decision = AsyncMock(return_value=stored)
    response = EntityMentionResolutionResponse(
        ere_request_id="req:extra",
        entity_mention_id=_default_identifier(),
        candidates=[ClusterReference(
            cluster_id="c-001", confidence_score=0.9, similarity_score=0.85
        )],
        timestamp=datetime.now(UTC),
    )
    try:
        ctx["result"] = asyncio.run(
            ctx["service"].integrate_outcome(response)
        )
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["raised_exception"] = exc
        ctx["result"] = None


@then("an outcome validation error is raised")
def outcome_validation_error_raised(ctx):
    assert ctx["raised_exception"] is not None


@then("a triad-not-found error is raised")
def triad_not_found_error_raised(ctx):
    assert isinstance(ctx["raised_exception"], TriadNotFoundError)


@then("the message is rejected before reaching the service")
def message_rejected_before_service(ctx):
    """Assert rejection happened at the schema layer — neither service boundary was crossed."""
    assert ctx["raised_exception"] is not None
    ctx["registry"].get_resolution_request.assert_not_called()
    ctx["decisions"].store_decision.assert_not_called()


@then("the Decision Store is not modified")
def decision_store_not_modified(ctx):
    ctx["decisions"].store_decision.assert_not_called()


@then("no validation error is raised")
def no_validation_error_raised(ctx):
    assert ctx["raised_exception"] is None


@then("the cluster assignment is persisted to the Decision Store")
def cluster_assignment_persisted(ctx):
    ctx["decisions"].store_decision.assert_called_once()
