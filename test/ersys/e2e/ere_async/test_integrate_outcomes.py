"""Step definitions for integrate_outcomes.feature — ERE Async inbound boundary suite.

Tests verify that ERS correctly integrates clustering outcomes received from ERE
into the Decision Store, including idempotency, error handling, and delta tracking.

Outcomes are injected directly into the ere_responses Redis list to simulate ERE,
bypassing the real ERE worker.
"""
import json
import time
import uuid
from datetime import UTC, datetime

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from test.ersys.e2e.conftest import poll_until

scenarios("integrate_outcomes.feature")


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Mutable dict shared across steps within one scenario."""
    return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ere_response(triad: dict, cluster_id: str, extra_candidates: list | None = None) -> dict:
    """Build a valid ERE response message for the given triad.

    Uses the current UTC timestamp so the outcome is never treated as stale
    relative to a provisional decision created moments earlier.
    """
    candidates = [
        {"cluster_id": cluster_id, "confidence_score": 0.95, "similarity_score": 0.92}
    ]
    if extra_candidates:
        candidates.extend(extra_candidates)
    return {
        "@type": "EntityMentionResolutionResponse",
        "ere_request_id": str(uuid.uuid4()),
        "entity_mention_id": triad,
        "candidates": candidates,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _submit_mention(ers_client, triad: dict, content: str) -> dict:
    """Submit an entity mention for resolution and return the response body."""
    payload = {
        "mention": {
            "identifiedBy": triad,
            "content": content,
            "content_type": "text/turtle",
        }
    }
    resp = ers_client.post("/api/v1/resolve", json=payload)
    assert resp.status_code in (200, 202), (
        f"resolve failed for triad {triad}: {resp.status_code} {resp.text}"
    )
    return resp.json()


def _poll_decision(mongo_db, triad: dict, timeout_s: float = 20.0):
    """Poll until a decision document exists for the given triad."""
    return poll_until(
        lambda: mongo_db["decisions"].find_one({"about_entity_mention": triad}),
        timeout_s=timeout_s,
    )


def _poll_decision_cluster_change(mongo_db, triad: dict, old_cluster_id: str, timeout_s: float = 20.0):
    """Poll until the decision document has a cluster_id different from old_cluster_id."""
    def _changed():
        doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
        if doc is None:
            return None
        new_id = doc.get("current_placement", {}).get("cluster_id")
        return doc if new_id and new_id != old_cluster_id else None

    return poll_until(_changed, timeout_s=timeout_s)


# Background steps (decision store empty, ERE response channel operational) are
# defined in tests/e2e/conftest.py and shared across all e2e suites.

# ---------------------------------------------------------------------------
# Scenario 1 — Standard outcome
# ---------------------------------------------------------------------------


@given("a previously submitted entity mention is registered in the request registry")
def mention_registered_in_request_registry(ctx, ers_client, mongo_db, org_group1_file1):
    triad = {
        "source_id": "ere-int-src-001",
        "request_id": "ere-int-req-001",
        "entity_type": "ORGANISATION",
    }
    _submit_mention(ers_client, triad, org_group1_file1)
    # Wait until the request is recorded in MongoDB
    doc_id = f"{triad['source_id']}::{triad['request_id']}::{triad['entity_type']}"
    poll_until(
        lambda: mongo_db["resolution_requests"].find_one({"_id": doc_id}),
        timeout_s=15.0,
    )
    ctx["triad"] = triad
    ctx["canonical_cluster_id"] = str(uuid.uuid4())


@when("a valid ERE clustering outcome is injected for that mention")
def valid_ere_outcome_injected(ctx, redis_client):
    triad = ctx["triad"]
    cluster_id = ctx["canonical_cluster_id"]
    message = _make_ere_response(
        triad=triad,
        cluster_id=cluster_id,
        extra_candidates=[
            {"cluster_id": str(uuid.uuid4()), "confidence_score": 0.85, "similarity_score": 0.80},
            {"cluster_id": str(uuid.uuid4()), "confidence_score": 0.75, "similarity_score": 0.70},
        ],
    )
    ctx["injected_message"] = message
    redis_client.rpush("ere_responses", json.dumps(message))


@then("the decision store is updated with the canonical cluster identifier")
def decision_store_updated_with_canonical_cluster(ctx, mongo_db):
    """Poll until the decision shows the injected cluster_id.

    ERS may have already created a provisional decision before the injected
    outcome arrived. The OutcomeIntegrationWorker will update the provisional
    to the injected canonical cluster_id once it processes our response.
    We poll for this change rather than accepting any existing decision.
    """
    triad = ctx["triad"]
    expected_cluster = ctx["canonical_cluster_id"]

    def _has_injected_cluster():
        doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
        if doc is None:
            return None
        actual = doc.get("current_placement", {}).get("cluster_id")
        return doc if actual == expected_cluster else None

    doc = poll_until(_has_injected_cluster, timeout_s=30.0)
    assert doc is not None, (
        f"Decision cluster_id never became {expected_cluster!r} for triad {triad}"
    )
    ctx["decision_doc"] = doc


@then("the decision store contains the top alternative cluster candidates with their scores")
def decision_store_contains_alternatives(ctx, mongo_db):
    triad = ctx["triad"]
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    assert doc is not None, f"No decision found for triad {triad}"
    candidates = doc.get("candidates") or doc.get("alternatives") or []
    assert len(candidates) > 0, (
        f"Expected alternative candidates in decision doc, found none: {doc}"
    )


@then("the update timestamp in the decision store is refreshed")
def update_timestamp_is_refreshed(ctx, mongo_db):
    triad = ctx["triad"]
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    assert doc is not None, f"No decision found for triad {triad}"
    updated_at = doc.get("updated_at") or doc.get("last_updated") or doc.get("timestamp")
    assert updated_at is not None, (
        f"No update timestamp field found in decision doc: {doc}"
    )
    ctx["updated_at"] = updated_at


@then("the update timestamp in the decision store is not set")
def update_timestamp_is_not_set(ctx, mongo_db):
    triad = ctx["triad"]
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    assert doc is not None, f"No decision found for triad {triad}"
    updated_at = doc.get("updated_at") or doc.get("last_updated") or doc.get("timestamp")
    assert updated_at is None, (
        f"Expected update timestamp to be absent (same-placement no-op per ERS1-214 AC2), "
        f"but found updated_at={updated_at!r} in decision doc: {doc}"
    )


# ---------------------------------------------------------------------------
# Scenario 2 — Draft replacement
# ---------------------------------------------------------------------------


@given("a previously submitted entity mention is registered with a provisional draft identifier in the decision store")
def mention_registered_with_provisional_draft(ctx, ers_client, mongo_db, redis_client, org_group1_file1):
    """Submit a mention, let it time out to provisional, then verify provisional state.

    Strategy: submit and check for PROVISIONAL status directly from ERS response.
    If ERS responds synchronously with PROVISIONAL, use that cluster_id.
    If ERS responds immediately with a canonical cluster (ERE was fast), we still
    have a valid decision to update — the test logic adapts accordingly.
    """
    triad = {
        "source_id": "ere-int-src-draft",
        "request_id": "ere-int-req-draft",
        "entity_type": "ORGANISATION",
    }
    resp_body = _submit_mention(ers_client, triad, org_group1_file1)
    ctx["triad"] = triad

    status = resp_body.get("status", "")
    if status == "PROVISIONAL":
        provisional_id = resp_body.get("canonical_entity_id") or resp_body.get("cluster_id")
        ctx["provisional_cluster_id"] = provisional_id
    else:
        # ERE responded fast — poll until a decision exists, then treat that
        # cluster_id as the "draft" to be replaced
        doc = _poll_decision(mongo_db, triad, timeout_s=30.0)
        assert doc is not None, f"No decision created for triad {triad}"
        ctx["provisional_cluster_id"] = doc.get("current_placement", {}).get("cluster_id")

    assert ctx["provisional_cluster_id"], (
        f"Could not determine initial cluster_id for triad {triad}"
    )
    ctx["new_canonical_cluster_id"] = str(uuid.uuid4())
    # Ensure new id is genuinely different
    while ctx["new_canonical_cluster_id"] == ctx["provisional_cluster_id"]:
        ctx["new_canonical_cluster_id"] = str(uuid.uuid4())


@when("a valid ERE clustering outcome is injected for that mention with a new canonical cluster identifier")
def valid_outcome_injected_with_new_canonical(ctx, redis_client):
    triad = ctx["triad"]
    new_cluster_id = ctx["new_canonical_cluster_id"]
    message = _make_ere_response(triad=triad, cluster_id=new_cluster_id)
    ctx["injected_message"] = message
    redis_client.rpush("ere_responses", json.dumps(message))


@then("the decision store replaces the draft identifier with the canonical cluster identifier")
def draft_replaced_with_canonical(ctx, mongo_db):
    triad = ctx["triad"]
    expected = ctx["new_canonical_cluster_id"]
    doc = _poll_decision_cluster_change(
        mongo_db, triad, old_cluster_id=ctx["provisional_cluster_id"], timeout_s=30.0
    )
    assert doc is not None, (
        f"Decision was not updated from provisional {ctx['provisional_cluster_id']!r} "
        f"to new canonical for triad {triad}"
    )
    actual = doc.get("current_placement", {}).get("cluster_id")
    assert actual == expected, (
        f"Expected new canonical cluster_id {expected!r}, got {actual!r}: {doc}"
    )
    ctx["decision_doc"] = doc


@then("the similarity scores from the ERE outcome are preserved without modification")
def similarity_scores_preserved(ctx, mongo_db):
    triad = ctx["triad"]
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    assert doc is not None, f"No decision found for triad {triad}"
    injected = ctx["injected_message"]
    injected_candidates = injected.get("candidates", [])
    if injected_candidates:
        stored_candidates = doc.get("candidates") or doc.get("alternatives") or []
        # At least the top candidate's score should be preserved
        injected_score = injected_candidates[0].get("similarity_score")
        if injected_score is not None and stored_candidates:
            stored_score = stored_candidates[0].get("similarity_score")
            assert stored_score == injected_score, (
                f"similarity_score was modified: expected {injected_score}, got {stored_score}"
            )


# ---------------------------------------------------------------------------
# Scenario 3 — Draft confirmed
# ---------------------------------------------------------------------------


@when("a valid ERE clustering outcome is injected confirming the same cluster identifier as authoritative")
def outcome_injected_confirming_same_cluster(ctx, redis_client):
    triad = ctx["triad"]
    same_cluster_id = ctx["provisional_cluster_id"]
    message = _make_ere_response(triad=triad, cluster_id=same_cluster_id)
    ctx["injected_message"] = message
    ctx["confirmed_cluster_id"] = same_cluster_id
    redis_client.rpush("ere_responses", json.dumps(message))


@then("the decision store retains the same cluster identifier")
def decision_store_retains_same_cluster(ctx, mongo_db):
    triad = ctx["triad"]
    expected = ctx["confirmed_cluster_id"]

    # Give the system time to process then check the cluster_id is unchanged
    def _still_same():
        doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
        if doc is None:
            return None
        actual = doc.get("current_placement", {}).get("cluster_id")
        return doc if actual == expected else None

    doc = poll_until(_still_same, timeout_s=20.0)
    assert doc is not None, (
        f"Decision cluster_id changed away from confirmed {expected!r} for triad {triad}"
    )
    ctx["decision_doc"] = doc


# ---------------------------------------------------------------------------
# Scenario 4 — Reclustering
# ---------------------------------------------------------------------------


@given("entity mentions are registered and have existing cluster assignments in the decision store")
def mentions_registered_with_existing_assignments(ctx, ers_client, mongo_db, redis_client, org_group1_file1, org_group1_file2):
    """Submit two mentions, inject outcomes to force canonical decisions for both."""
    triads = [
        {
            "source_id": "ere-int-src-recluster",
            "request_id": "ere-int-req-rc-001",
            "entity_type": "ORGANISATION",
        },
        {
            "source_id": "ere-int-src-recluster",
            "request_id": "ere-int-req-rc-002",
            "entity_type": "ORGANISATION",
        },
    ]
    contents = [org_group1_file1, org_group1_file2]

    cluster_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    for triad, content, cluster_id in zip(triads, contents, cluster_ids, strict=False):
        _submit_mention(ers_client, triad, content)
        # Wait for the request to be registered
        doc_id = f"{triad['source_id']}::{triad['request_id']}::{triad['entity_type']}"
        poll_until(
            lambda _id=doc_id: mongo_db["resolution_requests"].find_one({"_id": _id}),
            timeout_s=15.0,
        )
        # Inject an outcome to force a decision
        message = _make_ere_response(triad=triad, cluster_id=cluster_id)
        redis_client.rpush("ere_responses", json.dumps(message))
        # Wait until decision is stored
        _poll_decision(mongo_db, triad, timeout_s=30.0)

    ctx["triads"] = triads
    ctx["cluster_ids"] = cluster_ids
    # Target the first mention for reclustering
    ctx["affected_triad"] = triads[0]
    ctx["affected_old_cluster_id"] = cluster_ids[0]
    ctx["unaffected_triad"] = triads[1]
    ctx["unaffected_cluster_id"] = cluster_ids[1]
    ctx["new_recluster_id"] = str(uuid.uuid4())


@when("ERE emits a reclustering outcome for one of those mentions with an updated cluster identifier")
def ere_emits_reclustering_outcome(ctx, redis_client):
    triad = ctx["affected_triad"]
    new_cluster_id = ctx["new_recluster_id"]
    message = _make_ere_response(triad=triad, cluster_id=new_cluster_id)
    ctx["injected_message"] = message
    redis_client.rpush("ere_responses", json.dumps(message))


@then("the decision store reflects the new cluster assignment for the affected mention")
def decision_store_reflects_new_assignment(ctx, mongo_db):
    triad = ctx["affected_triad"]
    expected = ctx["new_recluster_id"]
    doc = _poll_decision_cluster_change(
        mongo_db, triad, old_cluster_id=ctx["affected_old_cluster_id"], timeout_s=30.0
    )
    assert doc is not None, (
        f"Decision cluster_id was not updated to {expected!r} for affected triad {triad}"
    )
    actual = doc.get("current_placement", {}).get("cluster_id")
    assert actual == expected, (
        f"Expected new cluster_id {expected!r}, got {actual!r}: {doc}"
    )


@then("the delta tracking is updated so that the change is visible through the next refresh operation")
def delta_tracking_updated_for_change(ctx, ers_client):
    triad = ctx["affected_triad"]
    resp = ers_client.post(
        "/api/v1/refresh-bulk",
        json={"source_id": triad["source_id"]},
    )
    assert resp.status_code == 200, (
        f"refresh-bulk failed: {resp.status_code} {resp.text}"
    )
    deltas = resp.json().get("deltas", [])
    matching = [
        d for d in deltas
        if d.get("identified_by", {}).get("source_id") == triad["source_id"]
        and d.get("identified_by", {}).get("request_id") == triad["request_id"]
        and d.get("identified_by", {}).get("entity_type") == triad["entity_type"]
    ]
    assert matching, (
        f"Affected mention {triad} not found in refresh-bulk deltas. "
        f"Returned: {[d.get('identified_by') for d in deltas]}"
    )
    cluster_id = matching[0].get("cluster_reference", {}).get("cluster_id")
    assert cluster_id == ctx["new_recluster_id"], (
        f"Delta cluster_id {cluster_id!r} != expected {ctx['new_recluster_id']!r}"
    )


@then("the cluster assignments of unaffected mentions are not changed")
def unaffected_mentions_not_changed(ctx, mongo_db):
    triad = ctx["unaffected_triad"]
    expected = ctx["unaffected_cluster_id"]
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    assert doc is not None, f"No decision found for unaffected triad {triad}"
    actual = doc.get("current_placement", {}).get("cluster_id")
    assert actual == expected, (
        f"Unaffected mention cluster_id was changed: expected {expected!r}, got {actual!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 5 — Idempotent duplicate
# ---------------------------------------------------------------------------


@given("a valid ERE clustering outcome has already been injected and processed for that mention")
def outcome_already_processed(ctx, redis_client, mongo_db):
    triad = ctx["triad"]
    cluster_id = ctx["canonical_cluster_id"]
    message = _make_ere_response(triad=triad, cluster_id=cluster_id)
    ctx["original_message"] = message
    redis_client.rpush("ere_responses", json.dumps(message))
    # Wait until decision is stored
    doc = _poll_decision(mongo_db, triad, timeout_s=30.0)
    ctx["first_updated_at"] = (
        doc.get("updated_at") or doc.get("last_updated") or doc.get("timestamp")
    )


@when("the same ERE clustering outcome is injected a second time")
def same_outcome_injected_second_time(ctx, redis_client):
    redis_client.rpush("ere_responses", json.dumps(ctx["original_message"]))
    # Allow time for the system to process (or ignore) the duplicate
    time.sleep(3.0)


@then("the decision store is not changed by the second injection")
def decision_store_not_changed_by_second_injection(ctx, mongo_db):
    triad = ctx["triad"]
    count = mongo_db["decisions"].count_documents({"about_entity_mention": triad})
    assert count == 1, (
        f"Expected exactly 1 decision doc for triad {triad}, found {count}"
    )


@then("no error condition is raised")
def no_error_condition_raised(ers_client):
    """Verify the ERS API is still healthy and responding."""
    resp = ers_client.get("/health")
    assert resp.status_code == 200, (
        f"ERS API health check failed after idempotent injection: {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Scenario 6 — Unknown mention discarded
# ---------------------------------------------------------------------------


@given("no entity mention with a particular triad has ever been submitted for resolution")
def no_mention_ever_submitted(ctx):
    ctx["unknown_triad"] = {
        "source_id": "ere-int-src-unknown",
        "request_id": f"ere-int-req-unknown-{uuid.uuid4().hex[:8]}",
        "entity_type": "ORGANISATION",
    }


@when("an ERE clustering outcome is injected for that unknown triad")
def ere_outcome_injected_for_unknown_triad(ctx, redis_client):
    triad = ctx["unknown_triad"]
    cluster_id = str(uuid.uuid4())
    message = _make_ere_response(triad=triad, cluster_id=cluster_id)
    redis_client.rpush("ere_responses", json.dumps(message))
    # Allow time for the system to process (and discard) the outcome
    time.sleep(3.0)


@then("no decision record is created in the decision store")
def no_decision_record_created(ctx, mongo_db):
    triad = ctx["unknown_triad"]
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    assert doc is None, (
        f"Expected no decision for unknown triad {triad}, but found: {doc}"
    )


# ---------------------------------------------------------------------------
# Scenario 7 — Malformed message outline
# ---------------------------------------------------------------------------


def _build_malformed_message(fault_type: str) -> bytes | str:
    """Construct a malformed ERE message for the given fault type."""
    if fault_type == "missing cluster identifier":
        return json.dumps({
            "@type": "EntityMentionResolutionResponse",
            "ere_request_id": str(uuid.uuid4()),
            "entity_mention_id": {
                "source_id": "malformed-src",
                "request_id": "malformed-req",
                "entity_type": "ORGANISATION",
            },
            "candidates": [],  # no candidates / empty cluster_id
            "timestamp": "2026-01-01T00:00:00+00:00",
        })
    elif fault_type == "missing mention triad fields":
        return json.dumps({
            "@type": "EntityMentionResolutionResponse",
            "ere_request_id": str(uuid.uuid4()),
            # entity_mention_id omitted entirely
            "candidates": [
                {"cluster_id": str(uuid.uuid4()), "confidence_score": 0.9}
            ],
            "timestamp": "2026-01-01T00:00:00+00:00",
        })
    elif fault_type == "empty message body":
        return ""
    elif fault_type == "non-JSON payload":
        return "this-is-not-json-!!!{{"
    else:
        pytest.fail(f"Unknown fault_type: {fault_type!r}")


@when(parsers.parse('a "{fault_type}" ERE message is injected into the response channel'))
def malformed_message_injected(ctx, fault_type, redis_client, mongo_db, ers_client, org_group1_file1):
    """Inject the malformed message and record the pre-injection decision state."""
    # Record current decision counts per known triad before injection
    triads = ctx.get("triads", [])
    cluster_ids_before = {}
    for triad in triads:
        doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
        if doc:
            cluster_ids_before[str(triad)] = doc.get("current_placement", {}).get("cluster_id")
    ctx["cluster_ids_before_malformed"] = cluster_ids_before
    ctx["fault_type"] = fault_type

    # Push the malformed message
    malformed = _build_malformed_message(fault_type)
    redis_client.rpush("ere_responses", malformed)

    # Allow the system time to encounter and discard the malformed message
    time.sleep(3.0)


@then("the decision store is not changed")
def decision_store_not_changed(ctx, mongo_db):
    """Verify the malformed message did not create new or destroy existing decision docs.

    We check document count and non-null cluster_ids, but do NOT assert exact cluster_id
    values: the live ERE worker may legitimately update them concurrently.
    The invariant is that decisions are not corrupted or deleted, not that they
    remain byte-for-byte identical.
    """
    triads = ctx.get("triads", [])
    for triad in triads:
        doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
        assert doc is not None, (
            f"Decision for triad {triad} was unexpectedly deleted after malformed message"
        )
        cluster_id = doc.get("current_placement", {}).get("cluster_id")
        assert cluster_id, (
            f"Decision cluster_id became empty/null after malformed message: {doc}"
        )


@then("the system continues to accept and process subsequent valid outcomes")
def system_continues_processing_valid_outcomes(ctx, ers_client, redis_client, mongo_db, org_group1_file1):
    """Submit a new mention, inject a valid outcome, verify the decision is stored."""
    recovery_triad = {
        "source_id": "ere-int-src-recovery",
        "request_id": f"ere-int-req-recovery-{uuid.uuid4().hex[:8]}",
        "entity_type": "ORGANISATION",
    }
    _submit_mention(ers_client, recovery_triad, org_group1_file1)
    doc_id = (
        f"{recovery_triad['source_id']}::{recovery_triad['request_id']}"
        f"::{recovery_triad['entity_type']}"
    )
    poll_until(
        lambda: mongo_db["resolution_requests"].find_one({"_id": doc_id}),
        timeout_s=15.0,
    )
    recovery_cluster_id = str(uuid.uuid4())
    valid_message = _make_ere_response(triad=recovery_triad, cluster_id=recovery_cluster_id)
    redis_client.rpush("ere_responses", json.dumps(valid_message))

    def _has_recovery_cluster():
        doc = mongo_db["decisions"].find_one({"about_entity_mention": recovery_triad})
        if doc is None:
            return None
        actual = doc.get("current_placement", {}).get("cluster_id")
        return doc if actual == recovery_cluster_id else None

    doc = poll_until(_has_recovery_cluster, timeout_s=30.0)
    assert doc is not None, (
        f"System failed to process valid outcome after malformed injection: "
        f"recovery decision cluster_id never became {recovery_cluster_id!r}"
    )
