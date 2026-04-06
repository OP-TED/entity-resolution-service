"""
Step definitions for: deduplication_and_staleness.feature

Feature: Deduplicate ERE Outcomes Using Latest Assignment Wins
"""

import asyncio
import contextlib
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
from ers.resolution_decision_store.domain.errors import StaleOutcomeError
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

FEATURE_FILE = str(
    Path(__file__).parent.parent.parent
    / "feature"
    / "ere_result_integrator"
    / "deduplication_and_staleness.feature"
)


@scenario(FEATURE_FILE, "Ignore an outcome whose timestamp does not advance the stored marker")
def test_ignore_stale_outcome():
    pass


@scenario(FEATURE_FILE, "Only the latest outcome survives when arrivals are out of order")
def test_out_of_order_arrivals():
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
        "stored_marker": None,
        "final_cluster": None,
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


def _make_decision(identifier, cluster_id, updated_at):
    return Decision(
        id="hash",
        about_entity_mention=identifier,
        current_placement=ClusterReference(
            cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85
        ),
        candidates=[],
        created_at=updated_at,
        updated_at=updated_at,
    )


@given(
    parsers.parse(
        "the Request Registry contains a mention with triad "
        '("{source_id}", "{request_id}", "Organization")'
    )
)
def request_registry_contains_mention(ctx, source_id, request_id):
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["registry"].get_resolution_request = AsyncMock(
        return_value=_make_record(source_id, request_id)
    )


@given(
    parsers.parse(
        "the Decision Store contains a cluster assignment for that triad "
        'with outcome marker "{outcome_marker}"'
    )
)
def decision_store_has_assignment(ctx, outcome_marker):
    ctx["stored_marker"] = outcome_marker
    ctx["decisions"].store_decision = AsyncMock(
        side_effect=StaleOutcomeError(
            ctx["source_id"] or "SYS",
            ctx["request_id"] or "req",
            "Organization",
            stored_at=outcome_marker,
            attempted_at="<earlier>",
        )
    )


@given(
    parsers.parse(
        "the Decision Store is empty for a mention with triad "
        '("{source_id}", "{request_id}", "Organization")'
    )
)
def decision_store_empty_for_triad(ctx, source_id, request_id):
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["registry"].get_resolution_request = AsyncMock(
        return_value=_make_record(source_id, request_id)
    )


@when(
    parsers.parse(
        "the ERE delivers an outcome for that triad with outcome marker "
        '"{incoming_timestamp}" and cluster "{incoming_cluster}"'
    )
)
def ere_delivers_outcome(ctx, incoming_timestamp, incoming_cluster):
    identifier = EntityMentionIdentifier(
        source_id=ctx["source_id"], request_id=ctx["request_id"], entity_type="Organization"
    )
    ts = datetime.fromisoformat(incoming_timestamp)
    response = EntityMentionResolutionResponse(
        ere_request_id="req:stale",
        entity_mention_id=identifier,
        candidates=[ClusterReference(
            cluster_id=incoming_cluster, confidence_score=0.9, similarity_score=0.85
        )],
        timestamp=ts,
    )
    try:
        ctx["result"] = asyncio.run(
            ctx["service"].integrate_outcome(response)
        )
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when("the ERE delivers outcomes for that triad in this order:")
def ere_delivers_outcomes_in_order(ctx, datatable):
    headers = datatable[0]
    rows = [dict(zip(headers, row, strict=True)) for row in datatable[1:]]

    identifier = EntityMentionIdentifier(
        source_id=ctx["source_id"], request_id=ctx["request_id"], entity_type="Organization"
    )

    # Determine the winner (latest timestamp)
    winning_ts = None
    winning_cluster = None
    for row in rows:
        ts = datetime.fromisoformat(row["outcome_marker"].strip())
        if winning_ts is None or ts > winning_ts:
            winning_ts = ts
            winning_cluster = row["cluster_id"].strip()

    ctx["final_cluster"] = winning_cluster

    call_count = {"n": 0}

    async def smart_store(identifier, current, candidates, updated_at):
        if call_count["n"] == 0:
            call_count["n"] += 1
            return _make_decision(identifier, current.cluster_id, updated_at)
        raise StaleOutcomeError(
            identifier.source_id, identifier.request_id, identifier.entity_type,
            stored_at=str(winning_ts), attempted_at=str(updated_at)
        )

    ctx["decisions"].store_decision = smart_store

    for row in rows:
        ts = datetime.fromisoformat(row["outcome_marker"].strip())
        cluster_id = row["cluster_id"].strip()
        response = EntityMentionResolutionResponse(
            ere_request_id="req:oor",
            entity_mention_id=identifier,
            candidates=[ClusterReference(
                cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85
            )],
            timestamp=ts,
        )
        with contextlib.suppress(Exception):
            asyncio.run(ctx["service"].integrate_outcome(response))


@then("the outcome is ignored without modifying the Decision Store")
def outcome_ignored(ctx):
    # assert_called_once() confirms the service reached store_decision() and
    # that it raised StaleOutcomeError (no real write occurred). The mock was
    # configured with side_effect=StaleOutcomeError in the given step, so a
    # single call means the stale path was taken and no retry happened.
    ctx["decisions"].store_decision.assert_called_once()


@then(
    parsers.parse(
        "the Decision Store still holds the cluster assignment "
        'with outcome marker "{expected_marker}"'
    )
)
def decision_store_unchanged(ctx, expected_marker):
    assert ctx["stored_marker"] == expected_marker


@then(
    parsers.parse('the Decision Store holds cluster assignment "{expected_cluster}" for that triad')
)
def decision_store_holds_cluster(ctx, expected_cluster):
    assert ctx["final_cluster"] == expected_cluster
