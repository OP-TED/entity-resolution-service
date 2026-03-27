"""
Step definitions for: outcome_acceptance.feature

Feature: Accept and Persist ERE Resolution Outcomes
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from erspec.models.ere import EntityMentionResolutionResponse
from pytest_bdd import given, parsers, scenario, then, when

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
    / "outcome_acceptance.feature"
)


@scenario(FEATURE_FILE, "Accept a valid solicited resolution outcome")
def test_accept_valid_solicited_outcome():
    pass


@scenario(FEATURE_FILE, "Accept an unsolicited reclustering outcome initiated by the ERE")
def test_accept_unsolicited_reclustering_outcome():
    pass


@scenario(FEATURE_FILE, "Replace alternative candidates wholesale when a new outcome arrives")
def test_replace_alternatives_wholesale():
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
        "source_id": None,
        "request_id": None,
        "result": None,
        "raised_exception": None,
    }


def _make_record(source_id, request_id):
    return ResolutionRequestRecord(
        identifiedBy=EntityMentionIdentifier(
            source_id=source_id, request_id=request_id, entity_type="Organization"
        ),
        content="rdf",
        content_type="text/turtle",
        content_hash="a" * 64,
        received_at=datetime.now(UTC),
    )


def _make_decision(identifier, cluster_ref, candidates):
    now = datetime.now(UTC)
    return Decision(
        id="hash",
        about_entity_mention=identifier,
        current_placement=cluster_ref,
        candidates=candidates,
        created_at=now,
        updated_at=now,
    )


@given("the Decision Store contains no prior cluster assignment for that triad")
def decision_store_is_empty(ctx):
    ctx["decisions"].store_decision = AsyncMock(return_value=None)


@given(
    parsers.parse(
        'the mention with triad ("{source_id}", "{request_id}", "Organization") '
        "exists in the Request Registry"
    )
)
def mention_exists_in_registry(ctx, source_id, request_id):
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["registry"].get_resolution_request = AsyncMock(
        return_value=_make_record(source_id, request_id)
    )


@given(
    parsers.parse('the Decision Store "{prior_state}" a prior cluster assignment for that triad')
)
def decision_store_prior_state(ctx, prior_state):
    pass


@given(
    parsers.parse(
        "the Decision Store contains an existing cluster assignment "
        'with "{prior_candidate_count}" alternative candidates'
    )
)
def decision_store_has_prior_candidates(ctx, prior_candidate_count):
    pass


@when(
    parsers.parse(
        "the ERE publishes a solicited outcome for that triad with outcome timestamp "
        '"{outcome_timestamp}", primary cluster "{cluster_id}", '
        'and "{candidate_count}" alternative candidates'
    )
)
def ere_publishes_solicited_outcome(ctx, outcome_timestamp, cluster_id, candidate_count):
    n = int(candidate_count)
    primary = ClusterReference(cluster_id=cluster_id, confidence_score=0.95, similarity_score=0.90)
    alternatives = [
        ClusterReference(cluster_id=f"alt-{i}", confidence_score=0.4, similarity_score=0.35)
        for i in range(n)
    ]
    identifier = EntityMentionIdentifier(
        source_id=ctx["source_id"], request_id=ctx["request_id"], entity_type="Organization"
    )
    ctx["decisions"].store_decision = AsyncMock(
        return_value=_make_decision(identifier, primary, alternatives)
    )
    response = EntityMentionResolutionResponse(
        ere_request_id=f"{ctx['request_id']}:001",
        entity_mention_id=identifier,
        candidates=[primary] + alternatives,
        timestamp=datetime.fromisoformat(outcome_timestamp),
    )
    try:
        ctx["result"] = asyncio.run(
            ctx["service"].integrate_outcome(response)
        )
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when(
    parsers.parse(
        'the ERE publishes an unsolicited outcome identified by "{ere_request_id}" '
        'with outcome timestamp "{outcome_timestamp}" and primary cluster "{cluster_id}"'
    )
)
def ere_publishes_unsolicited_outcome(ctx, ere_request_id, outcome_timestamp, cluster_id):
    primary = ClusterReference(cluster_id=cluster_id, confidence_score=0.95, similarity_score=0.90)
    identifier = EntityMentionIdentifier(
        source_id=ctx["source_id"], request_id=ctx["request_id"], entity_type="Organization"
    )
    ctx["decisions"].store_decision = AsyncMock(
        return_value=_make_decision(identifier, primary, [])
    )
    response = EntityMentionResolutionResponse(
        ere_request_id=ere_request_id,
        entity_mention_id=identifier,
        candidates=[primary],
        timestamp=datetime.fromisoformat(outcome_timestamp),
    )
    try:
        ctx["result"] = asyncio.run(
            ctx["service"].integrate_outcome(response)
        )
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when(
    parsers.parse(
        "the ERE publishes a new outcome for that triad with outcome timestamp "
        '"{outcome_timestamp}" and "{new_candidate_count}" alternative candidates'
    )
)
def ere_publishes_new_outcome_with_candidates(ctx, outcome_timestamp, new_candidate_count):
    n = int(new_candidate_count)
    primary = ClusterReference(cluster_id="cluster-new", confidence_score=0.95, similarity_score=0.90)
    new_candidates = [
        ClusterReference(cluster_id=f"new-alt-{i}", confidence_score=0.4, similarity_score=0.35)
        for i in range(n)
    ]
    identifier = EntityMentionIdentifier(
        source_id=ctx["source_id"], request_id=ctx["request_id"], entity_type="Organization"
    )
    ctx["decisions"].store_decision = AsyncMock(
        return_value=_make_decision(identifier, primary, new_candidates)
    )
    ctx["new_candidate_count"] = n
    response = EntityMentionResolutionResponse(
        ere_request_id=f"{ctx['request_id']}:002",
        entity_mention_id=identifier,
        candidates=[primary] + new_candidates,
        timestamp=datetime.fromisoformat(outcome_timestamp),
    )
    try:
        ctx["result"] = asyncio.run(
            ctx["service"].integrate_outcome(response)
        )
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@then(
    parsers.parse(
        'the Decision Store is updated with cluster assignment "{cluster_id}" for that triad'
    )
)
def decision_store_updated_with_cluster(ctx, cluster_id):
    assert ctx["raised_exception"] is None, f"Unexpected exception: {ctx['raised_exception']}"
    ctx["decisions"].store_decision.assert_called_once()
    call_kwargs = ctx["decisions"].store_decision.call_args.kwargs
    assert call_kwargs["current"].cluster_id == cluster_id


@then(parsers.parse('the outcome marker stored in the Decision Store equals "{outcome_timestamp}"'))
def outcome_marker_equals(ctx, outcome_timestamp):
    call_kwargs = ctx["decisions"].store_decision.call_args.kwargs
    assert call_kwargs["updated_at"] == datetime.fromisoformat(outcome_timestamp)


@then(
    parsers.parse(
        'all "{candidate_count}" alternative candidates are stored '
        "alongside the primary cluster assignment"
    )
)
def alternative_candidates_stored(ctx, candidate_count):
    call_kwargs = ctx["decisions"].store_decision.call_args.kwargs
    assert len(call_kwargs["candidates"]) == int(candidate_count)


@then(
    parsers.parse(
        'the Decision Store stores exactly "{new_candidate_count}" '
        "alternative candidates for that triad"
    )
)
def decision_store_has_exact_candidate_count(ctx, new_candidate_count):
    call_kwargs = ctx["decisions"].store_decision.call_args.kwargs
    assert len(call_kwargs["candidates"]) == int(new_candidate_count)


@then("no candidates from the prior outcome are retained")
def no_prior_candidates_retained(ctx):
    assert ctx["decisions"].store_decision.call_count == 1
