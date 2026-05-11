"""Step definitions for tests/e2e/ers_api/cluster_assignment_lookup.feature.

Implements:
  - Lookup previously resolved mention → 200 (scenario 1)
  - Lookup unknown triad → 404 (scenario 2)
  - Lookup provisional mention → provisional cluster_id (scenario 3)
  - refreshBulk with updated mentions (scenario 4)
  - refreshBulk with no updates (scenario 5)

The provisional scenario (3) injects a decision directly into MongoDB with
a provisional cluster_id (SHA256 of triad) to avoid needing timing control
over the ERE execution window.
"""
import datetime as dt
import json
import uuid

import pytest
from pytest_bdd import given, scenario, then, when

from test.ersys.e2e.conftest import poll_until
from test.ersys.e2e.ers_api.conftest import derive_provisional_id

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

@scenario(
    "cluster_assignment_lookup.feature",
    "Looking up a previously resolved mention returns its current cluster assignment",
)
def test_lookup_resolved_mention():
    pass


@scenario(
    "cluster_assignment_lookup.feature",
    "Looking up an entity mention that has never been submitted returns a not-found outcome",
)
def test_lookup_unknown_mention():
    pass


@scenario(
    "cluster_assignment_lookup.feature",
    "Looking up an entity mention that has a provisional draft identifier returns provisional status",
)
def test_lookup_provisional_mention():
    pass


@scenario(
    "cluster_assignment_lookup.feature",
    "refreshBulk returns only mentions whose cluster assignment changed since the last notification date",
)
def test_refresh_bulk_with_updates():
    pass


@scenario(
    "cluster_assignment_lookup.feature",
    "refreshBulk returns an empty collection when no cluster assignments have changed since the last notification date",
)
def test_refresh_bulk_no_updates():
    pass


# ---------------------------------------------------------------------------
# Shared context fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    """Mutable dictionary for intra-scenario shared state."""
    return {}


# ---------------------------------------------------------------------------
# Given steps — lookup scenarios
# ---------------------------------------------------------------------------

@given("an entity mention has been submitted and fully resolved by ERE")
def given_mention_submitted_and_resolved(ctx, ers_client, mongo_db, lookup_resolve_payload):
    """Submit a mention and wait for ERE to produce a canonical (non-provisional) decision."""
    resp = ers_client.post("/api/v1/resolve", json=lookup_resolve_payload)
    assert resp.status_code in (200, 202), (
        f"Expected 200 or 202 from /resolve, got {resp.status_code}. Body: {resp.json()}"
    )
    body = resp.json()
    ident = body["identified_by"]
    ctx["source_id"] = ident["source_id"]
    ctx["request_id"] = ident["request_id"]
    ctx["entity_type"] = ident["entity_type"]

    # Wait for a canonical (non-provisional) decision to appear in the store
    provisional = derive_provisional_id(
        ident["source_id"], ident["request_id"], ident["entity_type"]
    )

    def _canonical_decision_present():
        doc = mongo_db["decisions"].find_one({
            "about_entity_mention": {
                "source_id": ident["source_id"],
                "request_id": ident["request_id"],
                "entity_type": ident["entity_type"],
            }
        })
        if doc is None:
            return None
        if doc["current_placement"]["cluster_id"] != provisional:
            return doc
        return None

    decision = poll_until(_canonical_decision_present, timeout_s=30)
    ctx["expected_cluster_id"] = decision["current_placement"]["cluster_id"]


@given("no entity mention with the queried source identifier, request identifier, and entity type has been submitted")
def given_mention_never_submitted(ctx):
    ctx["source_id"] = "unknown-source-xyz"
    ctx["request_id"] = "unknown-request-xyz"
    ctx["entity_type"] = "ORGANISATION"


@given("an entity mention has been submitted but ERE did not respond within the execution window")
def given_mention_provisional(ctx, mongo_db):
    """Inject a provisional decision directly into MongoDB to simulate ERE timeout."""
    source_id = "test-source-provisional"
    request_id = "test-request-provisional"
    entity_type = "ORGANISATION"
    provisional_id = derive_provisional_id(source_id, request_id, entity_type)
    composite_registry_id = f"{source_id}::{request_id}::{entity_type}"

    # Insert a resolution_requests record (required for lookup to find the mention)
    mongo_db["resolution_requests"].insert_one({
        "_id": composite_registry_id,
        "identifiedBy": {
            "source_id": source_id,
            "request_id": request_id,
            "entity_type": entity_type,
        },
        "content": "stub content",
        "content_type": "text/turtle",
        "content_hash": "stub-hash",
        "received_at": dt.datetime.now(dt.UTC).isoformat(),
    })

    # Insert a decision with the provisional cluster_id (cluster_id == provisional_id)
    mongo_db["decisions"].insert_one({
        "_id": provisional_id,
        "about_entity_mention": {
            "source_id": source_id,
            "request_id": request_id,
            "entity_type": entity_type,
        },
        "current_placement": {
            "cluster_id": provisional_id,
            "confidence_score": 0.0,
            "similarity_score": 0.0,
        },
        "candidates": [],
        "created_at": dt.datetime.now(dt.UTC),
        "updated_at": dt.datetime.now(dt.UTC),
    })

    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = entity_type
    ctx["provisional_id"] = provisional_id


@given("the mention carries a provisional draft identifier")
def given_mention_carries_provisional_id(ctx):
    """State already established by the previous Given step."""
    assert "provisional_id" in ctx, (
        "Provisional decision was not injected — check the preceding Given step."
    )


# ---------------------------------------------------------------------------
# Given steps — refresh-bulk scenarios
# ---------------------------------------------------------------------------

@given('several entity mentions have been submitted and resolved for origin "test-source-001"')
def given_several_mentions_resolved_source001(ctx, ers_client, mongo_db, refresh_bulk_payload_1, refresh_bulk_payload_2):
    """Submit two mentions for test-source-001 and wait for canonical decisions."""
    payloads = [refresh_bulk_payload_1, refresh_bulk_payload_2]
    resolved_triads = []

    for payload in payloads:
        resp = ers_client.post("/api/v1/resolve", json=payload)
        assert resp.status_code in (200, 202), (
            f"Expected 200 or 202 from /resolve, got {resp.status_code}. Body: {resp.json()}"
        )
        ident = resp.json()["identified_by"]
        resolved_triads.append(ident)

    # Wait for canonical decisions for all submitted mentions
    for ident in resolved_triads:
        provisional = derive_provisional_id(
            ident["source_id"], ident["request_id"], ident["entity_type"]
        )

        def _canonical_present(ident=ident, provisional=provisional):
            doc = mongo_db["decisions"].find_one({
                "about_entity_mention": {
                    "source_id": ident["source_id"],
                    "request_id": ident["request_id"],
                    "entity_type": ident["entity_type"],
                }
            })
            if doc and doc["current_placement"]["cluster_id"] != provisional:
                return doc
            return None

        poll_until(_canonical_present, timeout_s=30)

    ctx["source_id"] = "test-source-001"
    ctx["resolved_triads"] = resolved_triads


@given('some of those mentions have had their cluster assignment updated since the last notification date')
def given_cluster_assignments_changed_since_last_notification(ctx, mongo_db, redis_client):
    """Inject a second ERE outcome with a different cluster_id for the first resolved mention.

    Under ERS1-214 R1, first-insert decisions have updated_at=None. Cold-start
    refresh-bulk only returns decisions where updated_at exists. By injecting a
    new ERE outcome (different cluster_id) we trigger the UPDATE path which sets
    updated_at, making the mention appear in the delta feed.
    """
    from datetime import UTC, datetime

    resolved_triads = ctx["resolved_triads"]
    target_triad = resolved_triads[0]

    current_doc = mongo_db["decisions"].find_one({"about_entity_mention": target_triad})
    assert current_doc is not None, (
        f"No decision found for {target_triad} — previous Given step did not resolve it"
    )
    current_cluster_id = current_doc["current_placement"]["cluster_id"]

    new_cluster_id = str(uuid.uuid4())
    assert new_cluster_id != current_cluster_id

    message = {
        "@type": "EntityMentionResolutionResponse",
        "ere_request_id": str(uuid.uuid4()),
        "entity_mention_id": target_triad,
        "candidates": [
            {"cluster_id": new_cluster_id, "confidence_score": 0.95, "similarity_score": 0.92}
        ],
        "timestamp": datetime.now(UTC).isoformat(),
    }
    redis_client.rpush("ere_responses", json.dumps(message))

    def _updated():
        doc = mongo_db["decisions"].find_one({"about_entity_mention": target_triad})
        if doc and doc.get("current_placement", {}).get("cluster_id") == new_cluster_id:
            return doc
        return None

    poll_until(_updated, timeout_s=30.0)
    ctx["changed_triad"] = target_triad
    ctx["new_cluster_id"] = new_cluster_id


@given('entity mentions have been submitted and resolved for origin "test-source-002"')
def given_mentions_resolved_source002(ctx, ers_client, mongo_db, refresh_bulk_payload_source2):
    """Submit one mention for test-source-002 and wait for a canonical decision."""
    resp = ers_client.post("/api/v1/resolve", json=refresh_bulk_payload_source2)
    assert resp.status_code in (200, 202), (
        f"Expected 200 or 202 from /resolve, got {resp.status_code}. Body: {resp.json()}"
    )
    ident = resp.json()["identified_by"]

    provisional = derive_provisional_id(
        ident["source_id"], ident["request_id"], ident["entity_type"]
    )

    def _canonical_present():
        doc = mongo_db["decisions"].find_one({
            "about_entity_mention": {
                "source_id": ident["source_id"],
                "request_id": ident["request_id"],
                "entity_type": ident["entity_type"],
            }
        })
        if doc and doc["current_placement"]["cluster_id"] != provisional:
            return doc
        return None

    poll_until(_canonical_present, timeout_s=30)
    ctx["source_id"] = "test-source-002"


@given('no cluster assignments have changed since the last notification date for "test-source-002"')
def given_no_cluster_changes_since_snapshot_source002(ctx, ers_client):
    """Call refresh-bulk once to set the last_snapshot to 'now'.

    After this first call the snapshot is updated to the current time. A second
    call in the When step will find no new deltas.
    """
    resp = ers_client.post("/api/v1/refresh-bulk", json={
        "source_id": "test-source-002",
        "limit": 1000,
        "continuation_cursor": None,
    })
    assert resp.status_code == 200, (
        f"Setup refresh-bulk call failed: {resp.status_code}. Body: {resp.json()}"
    )
    # After this call the snapshot is set — next call should return empty deltas


# ---------------------------------------------------------------------------
# When steps — lookup
# ---------------------------------------------------------------------------

@when("the Originator requests the cluster assignment for that entity mention")
def when_originator_requests_cluster_assignment(ctx, ers_client, mongo_db):
    ctx["decisions_count_before_lookup"] = mongo_db["decisions"].count_documents({})
    resp = ers_client.get("/api/v1/lookup", params={
        "source_id": ctx["source_id"],
        "request_id": ctx["request_id"],
        "entity_type": ctx["entity_type"],
    })
    ctx["response"] = resp
    ctx["response_body"] = resp.json()


@when('the Originator invokes refreshBulk for origin "test-source-001"')
def when_refresh_bulk_source001(ctx, ers_client):
    resp = ers_client.post("/api/v1/refresh-bulk", json={
        "source_id": "test-source-001",
        "limit": 1000,
        "continuation_cursor": None,
    })
    ctx["response"] = resp
    ctx["response_body"] = resp.json()


@when('the Originator invokes refreshBulk for origin "test-source-002"')
def when_refresh_bulk_source002(ctx, ers_client):
    resp = ers_client.post("/api/v1/refresh-bulk", json={
        "source_id": "test-source-002",
        "limit": 1000,
        "continuation_cursor": None,
    })
    ctx["response"] = resp
    ctx["response_body"] = resp.json()


# ---------------------------------------------------------------------------
# Then steps — lookup success
# ---------------------------------------------------------------------------

@then("the response confirms the mention is found")
def then_response_mention_found(ctx):
    status = ctx["response"].status_code
    assert status == 200, (
        f"Expected HTTP 200 for a found mention, got {status}. "
        f"Body: {ctx['response_body']}"
    )


@then("the response contains the canonical cluster identifier assigned by ERE")
def then_response_has_canonical_cluster_id(ctx):
    body = ctx["response_body"]
    cluster_ref = body.get("cluster_reference")
    assert cluster_ref is not None, (
        f"Expected 'cluster_reference' in lookup response. Body: {body}"
    )
    assert cluster_ref.get("cluster_id"), (
        f"Expected non-empty cluster_reference.cluster_id. Body: {body}"
    )
    expected = ctx.get("expected_cluster_id")
    if expected:
        assert cluster_ref["cluster_id"] == expected, (
            f"cluster_id in lookup response {cluster_ref['cluster_id']!r} does not match "
            f"the canonical cluster_id recorded at resolve time {expected!r}."
        )


@then("the response contains the entity type and request identifier")
def then_response_contains_triad_fields(ctx):
    body = ctx["response_body"]
    ident = body.get("identified_by")
    assert ident is not None, f"Expected 'identified_by' in lookup response. Body: {body}"
    assert ident.get("entity_type") == ctx["entity_type"], (
        f"entity_type mismatch: got {ident.get('entity_type')!r}, "
        f"expected {ctx['entity_type']!r}"
    )
    assert ident.get("request_id") == ctx["request_id"], (
        f"request_id mismatch: got {ident.get('request_id')!r}, "
        f"expected {ctx['request_id']!r}"
    )


@then("the decision store is not modified by the lookup")
def then_decisions_not_modified_by_lookup(ctx, mongo_db):
    count_before = ctx["decisions_count_before_lookup"]
    count_after = mongo_db["decisions"].count_documents({})
    assert count_after == count_before, (
        f"decisions collection changed after lookup: "
        f"expected {count_before}, got {count_after}."
    )


@then("the response indicates the mention was not found")
def then_response_mention_not_found(ctx):
    status = ctx["response"].status_code
    assert status == 404, (
        f"Expected HTTP 404 for unknown mention, got {status}. "
        f"Body: {ctx['response_body']}"
    )


@then("the decision store remains empty")
def then_decision_store_empty(ctx, mongo_db):
    count = mongo_db["decisions"].count_documents({})
    assert count == 0, (
        f"Expected empty decisions store after lookup of unknown mention, "
        f"but found {count} document(s)."
    )


@then("the response indicates the cluster assignment is provisional")
def then_response_indicates_provisional(ctx):
    """Confirm the cluster_id in the lookup response equals the provisional SHA256."""
    body = ctx["response_body"]
    cluster_ref = body.get("cluster_reference")
    assert cluster_ref is not None, (
        f"Expected 'cluster_reference' in lookup response. Body: {body}"
    )
    provisional_id = ctx["provisional_id"]
    assert cluster_ref["cluster_id"] == provisional_id, (
        f"Expected cluster_id={provisional_id!r} (provisional SHA256), "
        f"but got {cluster_ref['cluster_id']!r}. The response does not indicate "
        f"a provisional assignment."
    )


# ---------------------------------------------------------------------------
# Then steps — refresh-bulk with updates
# ---------------------------------------------------------------------------

@then("the response contains only the mentions whose cluster assignment changed after the last notification date")
def then_refresh_bulk_contains_changed_mentions(ctx):
    body = ctx["response_body"]
    assert ctx["response"].status_code == 200, (
        f"Expected HTTP 200 from refresh-bulk, got {ctx['response'].status_code}. "
        f"Body: {body}"
    )
    deltas = body.get("deltas", [])
    assert len(deltas) > 0, (
        f"Expected at least one delta in refresh-bulk response, but got empty deltas. "
        f"Body: {body}"
    )
    ctx["deltas"] = deltas


@then("each returned entry contains the request identifier, entity type, and canonical cluster identifier")
def then_each_delta_has_required_fields(ctx):
    for delta in ctx.get("deltas", []):
        ident = delta.get("identified_by")
        assert ident is not None, f"Delta missing 'identified_by'. Delta: {delta}"
        assert ident.get("request_id"), f"Delta 'identified_by' missing request_id. Delta: {delta}"
        assert ident.get("entity_type"), f"Delta 'identified_by' missing entity_type. Delta: {delta}"
        cluster_ref = delta.get("cluster_reference")
        assert cluster_ref is not None, f"Delta missing 'cluster_reference'. Delta: {delta}"
        assert cluster_ref.get("cluster_id"), (
            f"Delta 'cluster_reference' missing cluster_id. Delta: {delta}"
        )


@then('after the response is emitted the last notification date for "test-source-001" is updated in the delta tracking store')
def then_last_notification_updated_source001(ctx, mongo_db):
    doc = mongo_db["lookup_states"].find_one({"_id": "test-source-001"})
    assert doc is not None, (
        "Expected a lookup_states record for 'test-source-001' after refresh-bulk, "
        "but none was found."
    )
    assert doc.get("last_snapshot") is not None, (
        f"Expected 'last_snapshot' to be set in lookup_states for 'test-source-001'. "
        f"Document: {doc}"
    )


@then("the decision store records for unchanged mentions are not modified")
def then_unchanged_decisions_not_modified(ctx, mongo_db):
    # After refresh-bulk, the decisions collection must not have grown beyond
    # what was set up by the Given step (2 canonical decisions for test-source-001).
    count = mongo_db["decisions"].count_documents({"about_entity_mention.source_id": "test-source-001"})
    expected = len(ctx.get("resolved_triads", []))
    assert count == expected, (
        f"Expected {expected} decision(s) for test-source-001 after refresh-bulk, "
        f"but found {count}."
    )


# ---------------------------------------------------------------------------
# Then steps — refresh-bulk with no updates
# ---------------------------------------------------------------------------

@then("the response contains an empty collection of updated mentions")
def then_refresh_bulk_empty_deltas(ctx):
    body = ctx["response_body"]
    assert ctx["response"].status_code == 200, (
        f"Expected HTTP 200 from refresh-bulk, got {ctx['response'].status_code}. "
        f"Body: {body}"
    )
    deltas = body.get("deltas", None)
    assert deltas is not None, f"Expected 'deltas' key in response. Body: {body}"
    assert len(deltas) == 0, (
        f"Expected empty deltas (no changes since last snapshot), "
        f"but got {len(deltas)} delta(s). Body: {body}"
    )


@then('after the response is emitted the last notification date for "test-source-002" is still updated in the delta tracking store')
def then_last_notification_updated_source002(ctx, mongo_db):
    doc = mongo_db["lookup_states"].find_one({"_id": "test-source-002"})
    assert doc is not None, (
        "Expected a lookup_states record for 'test-source-002' after refresh-bulk, "
        "but none was found."
    )
    assert doc.get("last_snapshot") is not None, (
        f"Expected 'last_snapshot' to be set in lookup_states for 'test-source-002'. "
        f"Document: {doc}"
    )


@then("the decision store is not modified by the refreshBulk call")
def then_decisions_not_modified_by_refresh_bulk(ctx, mongo_db):
    # For test-source-002, only one decision was created in the Given step.
    count = mongo_db["decisions"].count_documents({"about_entity_mention.source_id": "test-source-002"})
    assert count == 1, (
        f"Expected exactly 1 decision for 'test-source-002' after refresh-bulk, "
        f"but found {count}."
    )
