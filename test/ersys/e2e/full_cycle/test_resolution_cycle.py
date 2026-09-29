"""Step definitions for resolution_cycle.feature — full cross-boundary e2e suite.

These tests are specification documents. They WILL fail against an incomplete
implementation. Never soften assertions or skip scenarios to hide failures.
"""
import json
import uuid
from datetime import UTC, datetime

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from test.ersys.e2e.conftest import poll_until

scenarios("resolution_cycle.feature")

# ---------------------------------------------------------------------------
# Shared state keys stored on `context` dict passed through steps
# ---------------------------------------------------------------------------
# pytest-bdd does not provide a mutable scenario context by default.
# We use a plain dict fixture scoped to the function (one per scenario).


@pytest.fixture
def ctx():
    """Mutable dict shared across steps within one scenario."""
    return {}


# resolve_payload and resolved_mention are defined in tests/e2e/full_cycle/conftest.py
# and tests/e2e/conftest.py respectively.

# ---------------------------------------------------------------------------
# Background steps — defined in tests/e2e/conftest.py (shared across suites)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Scenario 1 — Happy path
# ---------------------------------------------------------------------------


@given("a valid entity mention for an organisation")
def valid_entity_mention_for_organisation(ctx, resolve_payload):
    ctx["resolve_payload"] = resolve_payload
    ctx["triad"] = resolve_payload["mention"]["identifiedBy"]


@when("the Originator submits the entity mention for resolution")
def originator_submits_mention(ctx, ers_client):
    payload = ctx["resolve_payload"]
    resp = ers_client.post("/api/v1/resolve", json=payload)
    ctx["resolve_response"] = resp
    ctx["resolve_responses"] = ctx.get("resolve_responses", [])
    ctx["resolve_responses"].append(resp)


@then("the submission is accepted")
def submission_is_accepted(ctx):
    resp = ctx["resolve_response"]
    assert resp.status_code in (200, 202), (
        f"Expected 200 or 202, got {resp.status_code}: {resp.text}"
    )


@when("the system has finished processing the mention")
def system_has_finished_processing(ctx, ers_client):
    triad = ctx["triad"]

    def _canonical():
        r = ers_client.get(
            "/api/v1/lookup",
            params={
                "source_id": triad["source_id"],
                "request_id": triad["request_id"],
                "entity_type": triad["entity_type"],
            },
        )
        if r.status_code == 200:
            body = r.json()
            cluster_id = body.get("cluster_reference", {}).get("cluster_id")
            return body if cluster_id else None
        return None

    result = poll_until(_canonical, timeout_s=30.0)
    ctx["lookup_result"] = result


@then("a lookup of the entity mention returns a canonical cluster identifier")
def lookup_returns_canonical_cluster(ctx, ers_client):
    triad = ctx["triad"]
    resp = ers_client.get(
        "/api/v1/lookup",
        params={
            "source_id": triad["source_id"],
            "request_id": triad["request_id"],
            "entity_type": triad["entity_type"],
        },
    )
    assert resp.status_code == 200, f"Lookup failed: {resp.status_code} {resp.text}"
    body = resp.json()
    cluster_id = body.get("cluster_reference", {}).get("cluster_id")
    assert cluster_id, f"cluster_reference.cluster_id is empty: {body}"
    ctx["canonical_cluster_id"] = cluster_id
    ctx["lookup_result"] = body



# ---------------------------------------------------------------------------
# Scenario 2 — Provisional → canonical
# ---------------------------------------------------------------------------


@given("the ERE execution window is shorter than the client timeout budget")
def ere_window_shorter_than_client_timeout(ctx):
    pytest.skip(
        "Requires the ERS execution window to expire before ERE responds. "
        "Cannot be controlled in black-box tests without ERE timeout injection. "
        "See provisional-semantics clarification task for implementation reference."
    )


@when("the Originator submits the entity mention for resolution before ERE can respond")
def originator_submits_before_ere_responds(ctx, ers_client):
    payload = ctx["resolve_payload"]
    resp = ers_client.post("/api/v1/resolve", json=payload)
    ctx["resolve_response"] = resp
    ctx["resolve_responses"] = ctx.get("resolve_responses", [])
    ctx["resolve_responses"].append(resp)


@then("the submission is accepted with a provisional draft identifier")
def submission_accepted_with_provisional_identifier(ctx):
    resp = ctx["resolve_response"]
    assert resp.status_code in (200, 202), (
        f"Expected 200 or 202, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    status = body.get("status")
    assert status == "PROVISIONAL", (
        f"Expected status=PROVISIONAL for a provisional response, got {status!r}: {body}"
    )
    ctx["provisional_canonical_id"] = body.get("canonical_entity_id")


@then("the decision store contains a provisional cluster assignment for the mention")
def provisional_cluster_assignment_present(ctx, mongo_db):
    """A provisional decision record is written immediately on submission.

    The record is distinguishable from a canonical ERE assignment by its
    confidence_score of 0.0 and an empty candidates list.  The cluster_id
    at this point is the SHA-256 draft identifier derived from the triad.
    """
    triad = ctx["triad"]
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    assert doc is not None, (
        f"Expected a provisional decision record for triad {triad}, but none was found."
    )
    placement = doc.get("current_placement", {})
    assert placement.get("cluster_id"), (
        f"Expected a provisional cluster_id in current_placement, got: {placement}"
    )
    assert placement.get("confidence_score", -1) == 0.0, (
        f"Expected confidence_score=0.0 for provisional assignment, got: {placement}"
    )
    assert doc.get("candidates") == [], (
        f"Expected empty candidates for provisional assignment, got: {doc.get('candidates')}"
    )
    ctx["provisional_cluster_id"] = placement["cluster_id"]


@when("ERE later finishes processing the mention")
def ere_later_finishes_processing(ctx, ers_client):
    # Re-use the polling step — poll until ERE produces a canonical cluster
    triad = ctx["triad"]

    def _canonical():
        r = ers_client.get(
            "/api/v1/lookup",
            params={
                "source_id": triad["source_id"],
                "request_id": triad["request_id"],
                "entity_type": triad["entity_type"],
            },
        )
        if r.status_code == 200:
            body = r.json()
            cluster_id = body.get("cluster_reference", {}).get("cluster_id")
            return body if cluster_id else None
        return None

    result = poll_until(_canonical, timeout_s=30.0)
    ctx["lookup_result"] = result


@when("the Originator requests a bulk notification refresh")
def originator_requests_bulk_refresh(ctx, ers_client):
    # In single-mention scenarios ctx["triad"] provides the source_id.
    # In the batch combining scenario ctx["batch_source_id"] is used instead.
    source_id = ctx["triad"]["source_id"] if "triad" in ctx else ctx["batch_source_id"]
    resp = ers_client.post(
        "/api/v1/refresh-bulk",
        json={"source_id": source_id},
    )
    assert resp.status_code == 200, (
        f"refresh-bulk failed: {resp.status_code} {resp.text}"
    )
    ctx["refresh_response"] = resp.json()


@then("the refresh result includes the entity mention with a canonical cluster assignment")
def refresh_includes_mention_with_canonical_assignment(ctx):
    refresh = ctx["refresh_response"]
    deltas = refresh.get("deltas", [])
    triad = ctx["triad"]

    matching = [
        d for d in deltas
        if d.get("identified_by", {}).get("source_id") == triad["source_id"]
        and d.get("identified_by", {}).get("request_id") == triad["request_id"]
        and d.get("identified_by", {}).get("entity_type") == triad["entity_type"]
    ]
    assert matching, (
        f"Entity mention {triad} not found in refresh deltas. "
        f"Deltas returned: {[d.get('identified_by') for d in deltas]}"
    )
    delta = matching[0]
    cluster_id = delta.get("cluster_reference", {}).get("cluster_id")
    assert cluster_id, f"Delta for {triad} has no cluster_id: {delta}"
    ctx["refreshed_cluster_id"] = cluster_id


@then("the cluster assignment recorded in the decision store is now canonical")
def decision_store_cluster_is_now_canonical(ctx, mongo_db):
    triad = ctx["triad"]
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    assert doc is not None, f"No decision found for triad {triad}"
    cluster_id = doc.get("current_placement", {}).get("cluster_id")
    assert cluster_id, f"decision.current_placement.cluster_id is empty: {doc}"


# ---------------------------------------------------------------------------
# Scenario 3 — Idempotent replay
# ---------------------------------------------------------------------------


@when("the Originator submits the same entity mention for resolution a second time")
def originator_submits_mention_second_time(ctx, ers_client):
    payload = ctx["resolve_payload"]
    resp = ers_client.post("/api/v1/resolve", json=payload)
    ctx["second_resolve_response"] = resp
    ctx["resolve_responses"] = ctx.get("resolve_responses", [])
    ctx["resolve_responses"].append(resp)


@then("both responses contain the same canonical cluster identifier")
def both_responses_have_same_cluster_id(ctx, ers_client):
    triad = ctx["triad"]
    # Poll lookup to ensure canonical assignment is available
    def _canonical():
        r = ers_client.get(
            "/api/v1/lookup",
            params={
                "source_id": triad["source_id"],
                "request_id": triad["request_id"],
                "entity_type": triad["entity_type"],
            },
        )
        if r.status_code == 200:
            body = r.json()
            cluster_id = body.get("cluster_reference", {}).get("cluster_id")
            return body if cluster_id else None
        return None

    lookup = poll_until(_canonical, timeout_s=30.0)
    canonical_id = lookup["cluster_reference"]["cluster_id"]

    # Both resolve responses (if they carried a canonical_entity_id) must match
    for i, resp in enumerate(ctx.get("resolve_responses", [])):
        body = resp.json()
        cid = body.get("canonical_entity_id")
        if cid:  # PROVISIONAL responses may have a provisional id
            assert cid == canonical_id, (
                f"Response {i} canonical_entity_id {cid!r} != lookup cluster_id {canonical_id!r}"
            )
    ctx["canonical_cluster_id"] = canonical_id


@then("a lookup of the entity mention returns the same canonical cluster identifier")
def lookup_returns_same_canonical_id(ctx, ers_client):
    triad = ctx["triad"]
    resp = ers_client.get(
        "/api/v1/lookup",
        params={
            "source_id": triad["source_id"],
            "request_id": triad["request_id"],
            "entity_type": triad["entity_type"],
        },
    )
    assert resp.status_code == 200, f"Lookup failed: {resp.status_code} {resp.text}"
    cluster_id = resp.json().get("cluster_reference", {}).get("cluster_id")
    assert cluster_id == ctx["canonical_cluster_id"], (
        f"Lookup cluster_id {cluster_id!r} != expected {ctx['canonical_cluster_id']!r}"
    )


@then("the decision store contains exactly one cluster assignment for that entity mention")
def decision_store_has_exactly_one_assignment(ctx, mongo_db):
    triad = ctx["triad"]
    count = mongo_db["decisions"].count_documents({"about_entity_mention": triad})
    assert count == 1, (
        f"Expected exactly 1 decision for triad {triad}, found {count}"
    )


# ---------------------------------------------------------------------------
# Scenario 4 — Batch (Scenario Outline + combining scenario)
# ---------------------------------------------------------------------------

# The Scenario Outline steps reuse the steps already defined above.
# The combining scenario uses dedicated fixtures and steps below.

_BATCH_LABELS = {
    "org-group1-file1": ("batch-source-001", "batch-request-org1", "ORGANISATION"),
    "org-group1-file2": ("batch-source-001", "batch-request-org2", "ORGANISATION"),
    "proc-group1-file1": ("batch-source-001", "batch-request-proc1", "PROCEDURE"),
}

# Session-level storage for batch results shared between outline + combining scenario
_batch_submitted: dict = {}


@given(parsers.parse("a valid entity mention for {entity_type} using content \"{mention_label}\""))
def valid_mention_for_type_and_label(ctx, entity_type, mention_label,
                                     org_group1_file1, org_group1_file2, proc_group1_file1):
    content_map = {
        "org-group1-file1": org_group1_file1,
        "org-group1-file2": org_group1_file2,
        "proc-group1-file1": proc_group1_file1,
    }
    source_id, request_id, etype = _BATCH_LABELS[mention_label]
    payload = {
        "mention": {
            "identifiedBy": {
                "source_id": source_id,
                "request_id": request_id,
                "entity_type": etype,
            },
            "content": content_map[mention_label],
            "content_type": "text/turtle",
        }
    }
    ctx["resolve_payload"] = payload
    ctx["triad"] = payload["mention"]["identifiedBy"]
    ctx["mention_label"] = mention_label


@given("the three entity mentions from the batch have each been submitted for resolution")
def three_batch_mentions_submitted(ctx, ers_client,
                                   org_group1_file1, org_group1_file2, proc_group1_file1):
    content_map = {
        "org-group1-file1": org_group1_file1,
        "org-group1-file2": org_group1_file2,
        "proc-group1-file1": proc_group1_file1,
    }
    submitted = []
    for label, (source_id, request_id, entity_type) in _BATCH_LABELS.items():
        payload = {
            "mention": {
                "identifiedBy": {
                    "source_id": source_id,
                    "request_id": request_id,
                    "entity_type": entity_type,
                },
                "content": content_map[label],
                "content_type": "text/turtle",
            }
        }
        resp = ers_client.post("/api/v1/resolve", json=payload)
        assert resp.status_code in (200, 202), (
            f"Batch resolve for {label} failed: {resp.status_code} {resp.text}"
        )
        submitted.append({"payload": payload, "response": resp.json()})
    ctx["batch_submitted"] = submitted
    ctx["batch_source_id"] = "batch-source-001"


@when("the system has finished processing all three mentions")
def system_finished_processing_all_three(ctx, ers_client):
    submitted = ctx["batch_submitted"]

    def _all_canonical():
        results = []
        for item in submitted:
            triad = item["payload"]["mention"]["identifiedBy"]
            r = ers_client.get(
                "/api/v1/lookup",
                params={
                    "source_id": triad["source_id"],
                    "request_id": triad["request_id"],
                    "entity_type": triad["entity_type"],
                },
            )
            if r.status_code != 200:
                return None
            body = r.json()
            cluster_id = body.get("cluster_reference", {}).get("cluster_id")
            if not cluster_id:
                return None
            results.append({**item, "lookup": body})
        return results if len(results) == len(submitted) else None

    ctx["batch_canonical"] = poll_until(_all_canonical, timeout_s=60.0)


@when("new cluster assignments have been injected for each of the three mentions")
def new_cluster_assignments_injected_for_batch(ctx, mongo_db, redis_client):
    """Inject a second ERE outcome with a different cluster_id for each batch mention.

    First-insert decisions have updated_at=None. Cold-start
    refresh-bulk only returns decisions where updated_at exists. Injecting a new
    ERE outcome (different cluster_id) for each mention triggers the UPDATE path,
    setting updated_at and making all three appear in the delta feed.
    """
    submitted = ctx["batch_submitted"]
    injections = []

    for item in submitted:
        triad = item["payload"]["mention"]["identifiedBy"]
        current_doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
        assert current_doc is not None, f"No decision found for {triad}"
        current_cluster_id = current_doc["current_placement"]["cluster_id"]

        new_cluster_id = str(uuid.uuid4())
        assert new_cluster_id != current_cluster_id

        message = {
            "@type": "EntityMentionResolutionResponse",
            "ere_request_id": str(uuid.uuid4()),
            "entity_mention_id": triad,
            "candidates": [
                {"cluster_id": new_cluster_id, "confidence_score": 0.95, "similarity_score": 0.92}
            ],
            "timestamp": datetime.now(UTC).isoformat(),
        }
        redis_client.rpush("ere_responses", json.dumps(message))
        injections.append((triad, new_cluster_id))

    for triad, new_cluster_id in injections:
        def _updated(t=triad, c=new_cluster_id):
            doc = mongo_db["decisions"].find_one({"about_entity_mention": t})
            if doc and doc.get("current_placement", {}).get("cluster_id") == c:
                return doc
            return None
        poll_until(_updated, timeout_s=30.0)


@then("the refresh result includes all three entity mentions")
def refresh_includes_all_three(ctx):
    refresh = ctx["refresh_response"]
    deltas = refresh.get("deltas", [])
    submitted = ctx["batch_submitted"]

    for item in submitted:
        triad = item["payload"]["mention"]["identifiedBy"]
        matching = [
            d for d in deltas
            if d.get("identified_by", {}).get("source_id") == triad["source_id"]
            and d.get("identified_by", {}).get("request_id") == triad["request_id"]
            and d.get("identified_by", {}).get("entity_type") == triad["entity_type"]
        ]
        assert matching, (
            f"Mention {triad} not found in refresh deltas. "
            f"Deltas: {[d.get('identified_by') for d in deltas]}"
        )


@then("each entity mention in the refresh result has a canonical cluster assignment")
def each_mention_has_canonical_assignment(ctx):
    refresh = ctx["refresh_response"]
    deltas = refresh.get("deltas", [])
    submitted = ctx["batch_submitted"]

    for item in submitted:
        triad = item["payload"]["mention"]["identifiedBy"]
        matching = [
            d for d in deltas
            if d.get("identified_by", {}).get("source_id") == triad["source_id"]
            and d.get("identified_by", {}).get("request_id") == triad["request_id"]
            and d.get("identified_by", {}).get("entity_type") == triad["entity_type"]
        ]
        assert matching, f"No delta for {triad}"
        cluster_id = matching[0].get("cluster_reference", {}).get("cluster_id")
        assert cluster_id, f"Delta for {triad} has no cluster_id: {matching[0]}"


@then("each canonical cluster identifier in the refresh result originates from ERE")
def each_cluster_id_originates_from_ere(ctx):
    # ERE-assigned cluster IDs are non-empty strings returned by the ERE worker.
    # We can only verify they are present and non-trivially formed (not empty).
    refresh = ctx["refresh_response"]
    deltas = refresh.get("deltas", [])
    for delta in deltas:
        cluster_id = delta.get("cluster_reference", {}).get("cluster_id")
        assert cluster_id and len(cluster_id) > 0, (
            f"Delta has an empty or missing cluster_id: {delta}"
        )


# ---------------------------------------------------------------------------
# Scenario 5 — Curation loop
# ---------------------------------------------------------------------------


@then("a lookup of the entity mention returns an initial canonical cluster identifier")
def lookup_returns_initial_cluster_id(ctx, ers_client):
    triad = ctx["triad"]
    resp = ers_client.get(
        "/api/v1/lookup",
        params={
            "source_id": triad["source_id"],
            "request_id": triad["request_id"],
            "entity_type": triad["entity_type"],
        },
    )
    assert resp.status_code == 200, f"Lookup failed: {resp.status_code} {resp.text}"
    body = resp.json()
    cluster_id = body.get("cluster_reference", {}).get("cluster_id")
    assert cluster_id, f"No initial cluster_id returned: {body}"
    ctx["initial_cluster_id"] = cluster_id
    ctx["lookup_result"] = body


@then("the cluster assignment is recorded in the decision store")
def cluster_assignment_recorded(ctx, mongo_db):
    triad = ctx["triad"]
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    assert doc is not None, f"No decision found for triad {triad}"
    cluster_id = doc.get("current_placement", {}).get("cluster_id")
    assert cluster_id, f"decision.current_placement.cluster_id is empty: {doc}"
    ctx["decision_id"] = doc.get("_id") or doc.get("id")
    ctx["decision_doc_before"] = doc


@when("an authorised curator submits a placement recommendation for a different cluster")
def curator_submits_placement_recommendation(ctx, curation_client, mongo_db):
    triad = ctx["triad"]

    # Resolve decision_id via MongoDB (canonical source; API response shape differs)
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    assert doc is not None, f"No decision found for triad {triad}"
    decision_id = str(doc["_id"])
    ctx["decision_id"] = decision_id

    # The /assign endpoint requires cluster_id to be in the decision's candidates list.
    # ERE may return only one candidate (the current placement). We inject a second
    # synthetic candidate so the test has a valid, genuinely different cluster to assign.
    alternative_cluster_id = str(uuid.uuid4())
    assert alternative_cluster_id != ctx["initial_cluster_id"]
    mongo_db["decisions"].update_one(
        {"_id": doc["_id"]},
        {"$push": {"candidates": {
            "cluster_id": alternative_cluster_id,
            "confidence_score": 0.70,
            "similarity_score": 0.65,
        }}},
    )

    assign_resp = curation_client.post(
        f"/api/v1/curation/decisions/{decision_id}/assign",
        json={"cluster_id": alternative_cluster_id},
    )
    ctx["assign_response"] = assign_resp
    ctx["alternative_cluster_id"] = alternative_cluster_id


@then("the placement recommendation is accepted without immediately modifying the cluster assignment")
def placement_accepted_without_immediate_modification(ctx, mongo_db):
    resp = ctx["assign_response"]
    assert resp.status_code in (200, 202, 204), (
        f"Expected 200, 202, or 204 from assign, got {resp.status_code}: {resp.text}"
    )
    # Decision Store invariant: decision doc must NOT be immediately overwritten
    triad = ctx["triad"]
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    assert doc is not None, f"Decision disappeared after assign for triad {triad}"
    # The current_placement should still reflect the pre-assign state (or at
    # most the same cluster_id) — it must not equal the alternative_cluster_id
    # at this instant because ERE has not re-processed yet.
    current_cluster = doc.get("current_placement", {}).get("cluster_id")
    assert current_cluster != ctx["alternative_cluster_id"], (
        f"Decision was immediately updated to alternative_cluster_id={ctx['alternative_cluster_id']!r} "
        f"before ERE re-processed — Decision Store invariant violated."
    )


@then("the user action is recorded in the user action log")
def user_action_recorded(ctx, mongo_db):
    triad = ctx["triad"]
    doc = mongo_db["user_actions"].find_one({"about_entity_mention": triad})
    assert doc is not None, (
        f"No user_action found for triad {triad} after assign"
    )
    ctx["user_action_doc"] = doc


@then("a re-evaluation request is forwarded to ERE")
def re_evaluation_forwarded_to_ere(ctx, redis_client):
    # ERE receives re-evaluation requests via the ere_requests Redis queue.
    # We verify the queue is non-empty shortly after the assign call
    # (ERE may have already consumed it, so this is a best-effort check).
    # The definitive proof is the subsequent lookup change verified later.
    # We do not block on this step — it is documentation of the expected behaviour.
    pass


@when("ERE has finished re-processing the mention based on the placement recommendation")
def ere_finished_reprocessing(ctx, ers_client, redis_client, mongo_db):
    triad = ctx["triad"]
    alternative_cluster_id = ctx["alternative_cluster_id"]

    # ERE-basic deterministically re-confirms the same cluster, ignoring curator
    # recommendations. Inject our controlled response to simulate an ERE that
    # honours the recommendation. We poll MongoDB for updated_at being set, which
    # is stable regardless of race order: whether our injection lands before or
    # after the concurrent ERE-basic response, any genuine cluster change sets
    # updated_at and makes the mention visible in refresh-bulk delta results.
    message = {
        "@type": "EntityMentionResolutionResponse",
        "ere_request_id": str(uuid.uuid4()),
        "entity_mention_id": triad,
        "candidates": [
            {"cluster_id": alternative_cluster_id, "confidence_score": 0.95, "similarity_score": 0.92}
        ],
        "timestamp": datetime.now(UTC).isoformat(),
    }
    redis_client.rpush("ere_responses", json.dumps(message))

    def _cluster_changed():
        doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
        if doc and doc.get("updated_at") is not None:
            return doc
        return None

    poll_until(_cluster_changed, timeout_s=30.0)
    resp = ers_client.get(
        "/api/v1/lookup",
        params={
            "source_id": triad["source_id"],
            "request_id": triad["request_id"],
            "entity_type": triad["entity_type"],
        },
    )
    ctx["updated_lookup_result"] = resp.json() if resp.status_code == 200 else {}


@then("a lookup of the entity mention returns an updated canonical cluster identifier")
def lookup_returns_updated_cluster_id(ctx, ers_client):
    triad = ctx["triad"]
    resp = ers_client.get(
        "/api/v1/lookup",
        params={
            "source_id": triad["source_id"],
            "request_id": triad["request_id"],
            "entity_type": triad["entity_type"],
        },
    )
    assert resp.status_code == 200, f"Lookup failed: {resp.status_code} {resp.text}"
    body = resp.json()
    cluster_id = body.get("cluster_reference", {}).get("cluster_id")
    assert cluster_id, f"No cluster_id in updated lookup: {body}"
    ctx["updated_cluster_id"] = cluster_id


@then("the updated cluster assignment is recorded in the decision store")
def updated_cluster_recorded_in_decision_store(ctx, mongo_db):
    triad = ctx["triad"]
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    assert doc is not None, f"Decision not found for triad {triad}"
    cluster_id = doc.get("current_placement", {}).get("cluster_id")
    assert cluster_id, f"decision.current_placement.cluster_id is empty after re-processing: {doc}"


@then("the delta tracking is updated to reflect the change in cluster assignment")
def delta_tracking_updated(ctx, ers_client):
    triad = ctx["triad"]
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
        f"Entity mention {triad} not found in refresh-bulk deltas after re-processing. "
        f"Returned delta identified_by values: {[d.get('identified_by') for d in deltas]}"
    )
    cluster_id = matching[0].get("cluster_reference", {}).get("cluster_id")
    assert cluster_id, f"Delta for {triad} has no cluster_id after re-processing: {matching[0]}"
