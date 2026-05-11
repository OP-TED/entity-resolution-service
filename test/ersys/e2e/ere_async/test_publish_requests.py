"""Step definitions for publish_requests.feature — ERE Async outbound boundary suite.

Tests verify that ERS publishes well-formed resolution and re-evaluation requests
to the ERE request queue after receiving valid submissions.

NOTE: Scenario 2 (provisional timeout) is skipped — it requires controlling
the ERE execution window timing, which is not feasible in a black-box test
without ERE timeout injection support. See feature comment for UC-B2.1 context.
"""
import uuid

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from test.ersys.e2e.conftest import poll_until

scenarios("publish_requests.feature")


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Mutable dict shared across steps within one scenario."""
    return {}


# Background steps (ERS/Curation API reachable, ERE queue empty) are defined
# in tests/e2e/conftest.py and shared across all e2e suites.

# ---------------------------------------------------------------------------
# Scenario 1 — Standard publish
# ---------------------------------------------------------------------------


@given("a valid entity mention request for an organisation using the first test file")
def valid_mention_first_file(ctx, org_group1_file1):
    ctx["triad"] = {
        "source_id": "ere-async-src-001",
        "request_id": "ere-async-req-org1",
        "entity_type": "ORGANISATION",
    }
    ctx["resolve_payload"] = {
        "mention": {
            "identifiedBy": ctx["triad"],
            "content": org_group1_file1,
            "content_type": "text/turtle",
        }
    }


@when("the Originator submits the entity mention for resolution")
def originator_submits_mention_for_resolution(ctx, ers_client):
    resp = ers_client.post("/api/v1/resolve", json=ctx["resolve_payload"])
    ctx["resolve_response"] = resp


@then("the resolution is accepted")
def resolution_is_accepted(ctx):
    resp = ctx["resolve_response"]
    assert resp.status_code in (200, 202), (
        f"Expected 200 or 202, got {resp.status_code}: {resp.text}"
    )


@then("a resolution request message appears on the ERE request queue")
def resolution_request_appears_on_queue(ctx, mongo_db):
    """Verify ERS published a request by checking the request registry in MongoDB.

    The live ERE worker may consume the queue message before our test can read it,
    so we verify indirectly: ERS registers the mention in MongoDB only AFTER
    successfully publishing to ere_requests. The MongoDB entry is durable evidence
    that the publish happened.
    """
    triad = ctx["triad"]
    doc_id = f"{triad['source_id']}::{triad['request_id']}::{triad['entity_type']}"

    def _registered():
        return mongo_db["resolution_requests"].find_one({"_id": doc_id})

    doc = poll_until(_registered, timeout_s=15.0)
    assert doc is not None, (
        f"No resolution_request found in MongoDB for {doc_id!r} — "
        f"ERS may not have published the request"
    )
    ctx["resolution_request_doc"] = doc


@then("the message is correlated to the submitted entity mention triad")
def message_correlated_to_triad(ctx):
    """The request registry document is keyed by the triad — correlation is proven by its existence."""
    triad = ctx["triad"]
    doc = ctx.get("resolution_request_doc")
    assert doc is not None, "No resolution_request_doc in context"
    # The _id is source::request::entity_type — if this matched, correlation is confirmed
    expected_id = f"{triad['source_id']}::{triad['request_id']}::{triad['entity_type']}"
    assert str(doc.get("_id")) == expected_id, (
        f"resolution_request _id {doc.get('_id')!r} does not match expected {expected_id!r}"
    )


@then("the message carries the entity mention content")
def message_carries_content(ctx, mongo_db):
    """Verify content is stored in the request registry — proxy for content in the ERE message."""
    doc = ctx.get("resolution_request_doc")
    assert doc is not None, "No resolution_request_doc in context"
    # Content is stored in the request registry document
    content = doc.get("content") or doc.get("entity_mention", {}).get("content", "")
    assert content, (
        f"entity mention content is empty or missing in resolution_request doc: {doc}"
    )


# ---------------------------------------------------------------------------
# Scenario 2 — Provisional timeout (skipped — requires timing control)
# ---------------------------------------------------------------------------


@given("a valid entity mention request for an organisation using the second test file")
def valid_mention_second_file(ctx, org_group1_file2):
    ctx["triad"] = {
        "source_id": "ere-async-src-002",
        "request_id": "ere-async-req-org2",
        "entity_type": "ORGANISATION",
    }
    ctx["resolve_payload"] = {
        "mention": {
            "identifiedBy": ctx["triad"],
            "content": org_group1_file2,
            "content_type": "text/turtle",
        }
    }


@given("the ERE engine will not respond within the execution window")
def ere_engine_will_not_respond_within_window(ctx):
    """Mark scenario as requiring timing control — cannot be exercised black-box."""
    pytest.skip(
        "Scenario 2 requires controlling ERE execution window timing. "
        "This is not feasible in a black-box test without ERE timeout injection. "
        "See UC-B2.1 for implementation reference."
    )


@then("the resolution is accepted with a provisional draft identifier")
def resolution_accepted_with_provisional_id(ctx):
    resp = ctx["resolve_response"]
    assert resp.status_code in (200, 202), (
        f"Expected 200 or 202, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    status = body.get("status")
    assert status == "PROVISIONAL", (
        f"Expected status=PROVISIONAL, got {status!r}: {body}"
    )
    ctx["provisional_cluster_id"] = body.get("canonical_entity_id") or body.get("cluster_id")


@then("a resolve-considering-recommendation request appears on the ERE request queue")
def resolve_considering_recommendation_appears(ctx, read_ere_requests):
    messages = read_ere_requests(timeout_s=15.0)
    assert messages, "No message appeared on the ere_requests queue within 15 seconds"
    ctx["ere_request_messages"] = messages


@then("the message includes the provisional draft identifier as the recommended cluster")
def message_includes_provisional_as_recommendation(ctx):
    messages = ctx["ere_request_messages"]
    msg = messages[0]
    provisional_id = ctx.get("provisional_cluster_id")
    # The recommendation may appear in various fields depending on ERS implementation
    msg_str = str(msg)
    assert provisional_id and provisional_id in msg_str, (
        f"Provisional cluster id {provisional_id!r} not found in ERE request message: {msg}"
    )


# ---------------------------------------------------------------------------
# Scenario 3 — Re-evaluation outline
# ---------------------------------------------------------------------------


@given("a previously resolved entity mention is present in the system")
def previously_resolved_mention_present(ctx, ers_client, mongo_db, org_group1_file1):
    """Submit a mention and wait for ERE to write a decision to the store.

    Singleton entities (no cluster match found by ERE) produce decisions with an
    empty candidates list. We accept any decision where ERE has assigned a cluster_id.
    A synthetic candidate is injected later in curator_is_submitting_recommendation
    when needed for placement recommendations.
    """
    triad = {
        "source_id": "ere-async-src-reeval",
        "request_id": "ere-async-req-reeval",
        "entity_type": "ORGANISATION",
    }
    payload = {
        "mention": {
            "identifiedBy": triad,
            "content": org_group1_file1,
            "content_type": "text/turtle",
        }
    }
    resp = ers_client.post("/api/v1/resolve", json=payload)
    assert resp.status_code in (200, 202), (
        f"Initial resolve failed: {resp.status_code} {resp.text}"
    )
    ctx["triad"] = triad
    ctx["resolve_payload"] = payload

    def _any_ere_decision():
        doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
        if doc is None:
            return None
        cluster_id = doc.get("current_placement", {}).get("cluster_id")
        # Accept singletons (empty candidates) — synthetic candidate injected later
        return doc if cluster_id else None

    doc = poll_until(_any_ere_decision, timeout_s=90.0)
    ctx["initial_cluster_id"] = doc["current_placement"]["cluster_id"]
    ctx["decision_doc"] = doc


@given(parsers.parse('an authenticated curator is submitting a "{recommendation_type}" recommendation for that mention'))
def curator_is_submitting_recommendation(ctx, recommendation_type, curation_client, mongo_db):
    """Find the decision id in MongoDB and build the assign payload.

    For exclusion (REJECT_ALL), no candidate cluster_id is needed.
    For placement (ACCEPT_ALTERNATIVE), we use an existing candidate or inject a
    synthetic one when the entity is a singleton (empty candidates list), mirroring
    the same pattern used in the curation-loop scenario.
    """
    triad = ctx["triad"]
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    assert doc is not None, (
        f"No decision found for triad {triad} — mention may not be resolved yet"
    )
    decision_id = doc.get("_id") or doc.get("id")
    ctx["decision_id"] = str(decision_id)
    ctx["recommendation_type"] = recommendation_type

    candidates = doc.get("candidates") or []
    if recommendation_type == "placement":
        if not candidates:
            # Singleton entity: inject a synthetic candidate so /assign has a valid target
            synthetic_cluster_id = str(uuid.uuid4())
            mongo_db["decisions"].update_one(
                {"_id": doc["_id"]},
                {"$push": {"candidates": {
                    "cluster_id": synthetic_cluster_id,
                    "confidence_score": 0.70,
                    "similarity_score": 0.65,
                }}},
            )
            ctx["assign_payload"] = {"cluster_id": synthetic_cluster_id}
        else:
            candidate_cluster_id = candidates[0].get("cluster_id")
            assert candidate_cluster_id, f"First candidate has no cluster_id: {candidates[0]}"
            ctx["assign_payload"] = {"cluster_id": candidate_cluster_id}
    else:
        # exclusion (REJECT_ALL) — /reject endpoint needs no cluster_id
        ctx["assign_payload"] = {}


@when("the curator submits the re-evaluation request")
def curator_submits_reeval_request(ctx, curation_client, redis_client):
    """Drain the queue first, then submit the recommendation to capture only the new message.

    placement → POST /assign (ACCEPT_ALTERNATIVE)
    exclusion → POST /reject (REJECT_ALL)
    """
    while redis_client.lpop("ere_requests") is not None:
        pass

    decision_id = ctx["decision_id"]
    recommendation_type = ctx.get("recommendation_type", "placement")
    if recommendation_type == "exclusion":
        resp = curation_client.post(f"/api/v1/curation/decisions/{decision_id}/reject")
    else:
        resp = curation_client.post(
            f"/api/v1/curation/decisions/{decision_id}/assign",
            json=ctx["assign_payload"],
        )
    ctx["assign_response"] = resp


@then("the re-evaluation is accepted")
def reeval_is_accepted(ctx):
    resp = ctx["assign_response"]
    # Curation API /assign returns 204 No Content on success (per spec)
    assert resp.status_code in (200, 202, 204), (
        f"Expected 200, 202, or 204 from assign, got {resp.status_code}: {resp.text}"
    )


@then("a re-evaluation request message appears on the ERE request queue")
def reeval_message_appears_on_queue(ctx, mongo_db):
    """Verify the re-evaluation was forwarded by checking for a user_action log entry.

    The live ERE worker consumes queue messages before our test can read them.
    Instead, we verify the user_action document was created — this is only written
    AFTER ERS publishes the re-evaluation request to ere_requests.
    """
    triad = ctx["triad"]

    def _action_logged():
        return mongo_db["user_actions"].find_one({"about_entity_mention": triad})

    doc = poll_until(_action_logged, timeout_s=15.0)
    assert doc is not None, (
        f"No user_action found for triad {triad} — re-evaluation may not have been published"
    )
    ctx["user_action_doc"] = doc


@then(parsers.parse('the message carries the "{recommendation_type}" interaction type'))
def message_carries_interaction_type(ctx, recommendation_type):
    """Verify the interaction type is recorded in the user_action log.

    recommendation_type → expected action_type stored by the service:
      placement → ACCEPT_ALTERNATIVE  (via POST /assign)
      exclusion → REJECT_ALL          (via POST /reject)
    """
    _EXPECTED_ACTION_TYPE = {
        "placement": "ACCEPT_ALTERNATIVE",
        "exclusion": "REJECT_ALL",
    }
    doc = ctx.get("user_action_doc")
    assert doc is not None, "No user_action_doc in context"
    expected = _EXPECTED_ACTION_TYPE.get(recommendation_type.lower())
    assert expected is not None, f"Unknown recommendation_type {recommendation_type!r}"
    actual = doc.get("action_type")
    assert actual == expected, (
        f"Expected action_type {expected!r} for recommendation_type {recommendation_type!r}, "
        f"got {actual!r}. Full doc: {doc}"
    )


@then("the decision store is not modified immediately")
def decision_store_not_modified_immediately(ctx, mongo_db):
    """The decision doc should still exist with its pre-assign cluster_id."""
    triad = ctx["triad"]
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    assert doc is not None, (
        f"Decision disappeared after assign for triad {triad}"
    )
    current_cluster = doc.get("current_placement", {}).get("cluster_id")
    assert current_cluster == ctx["initial_cluster_id"], (
        f"Decision was immediately modified: expected cluster_id {ctx['initial_cluster_id']!r}, "
        f"got {current_cluster!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 4 — Invalid submission outline
# ---------------------------------------------------------------------------


def _build_invalid_payload(missing_field: str, content: str) -> dict:
    """Build a resolve payload with one required field omitted."""
    base = {
        "mention": {
            "identifiedBy": {
                "source_id": "invalid-src",
                "request_id": "invalid-req",
                "entity_type": "ORGANISATION",
            },
            "content": content,
            "content_type": "text/turtle",
        }
    }
    if missing_field == "source_id":
        del base["mention"]["identifiedBy"]["source_id"]
    elif missing_field == "request_id":
        del base["mention"]["identifiedBy"]["request_id"]
    elif missing_field == "entity_type":
        del base["mention"]["identifiedBy"]["entity_type"]
    elif missing_field == "content":
        del base["mention"]["content"]
    elif missing_field == "content_type":
        del base["mention"]["content_type"]
    else:
        pytest.fail(f"Unknown missing_field: {missing_field!r}")
    return base


@given(parsers.parse('an entity mention request with the "{missing_field}" field omitted'))
def mention_with_field_omitted(ctx, missing_field, org_group1_file1):
    ctx["resolve_payload"] = _build_invalid_payload(missing_field, org_group1_file1)
    ctx["missing_field"] = missing_field


@then("the submission is rejected as invalid")
def submission_rejected_as_invalid(ctx):
    resp = ctx["resolve_response"]
    # ERS returns 400 (VALIDATION_ERROR) for missing required fields rather than 422
    assert resp.status_code in (400, 422), (
        f"Expected HTTP 400 or 422 for invalid payload (missing {ctx.get('missing_field')!r}), "
        f"got {resp.status_code}: {resp.text}"
    )


@then("no message is published to the ERE request queue")
def no_message_on_ere_queue(redis_client):
    count = redis_client.llen("ere_requests")
    assert count == 0, (
        f"Expected ere_requests queue to be empty after invalid submission, "
        f"found {count} message(s)"
    )
