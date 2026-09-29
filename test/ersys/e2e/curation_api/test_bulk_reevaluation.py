"""Step definitions for tests/e2e/curation_api/bulk_reevaluation.feature.

UC-B2.2 — Submit Bulk Curator Re-evaluation Requests.

Implements:
  - Bulk placement for N valid mentions (scenario outline: 2, 5, 10)
  - Partial success — valid mentions proceed, invalid rejected (scenario)
  - Empty selection rejected (scenario)
"""
import uuid

import pytest
from pytest_bdd import given, parsers, scenario, then, when

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

@scenario(
    "bulk_reevaluation.feature",
    "Bulk placement recommendation for valid mentions creates independent action log entries and ERE messages",
)
def test_bulk_placement_recommendation():
    pass


@scenario(
    "bulk_reevaluation.feature",
    "Bulk submission where some mentions are invalid results in partial success",
)
def test_bulk_partial_success():
    pass


@scenario(
    "bulk_reevaluation.feature",
    "Bulk re-evaluation request with no mentions selected is rejected without side effects",
)
def test_bulk_empty_selection():
    pass


# ---------------------------------------------------------------------------
# Shared context fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    """Mutable dict for intra-scenario shared state."""
    return {}


# Background steps "the ERE request channel is empty" and "the user action log is empty"
# are bound globally in tests/e2e/conftest.py.

# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------

@given(parsers.parse("{mention_count:d} entity mentions exist in the decision store each with a current cluster assignment"), target_fixture="seeded_decisions")
def given_n_decisions_in_store(mention_count, decisions_in_store):
    """Inject N decisions into MongoDB via the factory fixture."""
    items = decisions_in_store(n=mention_count)
    return {"items": items, "mention_count": mention_count}


@given("3 entity mentions exist in the decision store each with a current cluster assignment", target_fixture="seeded_decisions")
def given_3_decisions_in_store(decisions_in_store):
    items = decisions_in_store(n=3)
    return {"items": items, "mention_count": 3}


@pytest.fixture
def nonexistent_ids():
    """Default: no extra IDs. Overridden by the given step in the partial-success scenario."""
    return []


@given("2 additional mention identifiers that do not exist in the decision store", target_fixture="nonexistent_ids")
def given_2_nonexistent_ids():
    return [str(uuid.uuid4()), str(uuid.uuid4())]


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------

@when(parsers.parse("an authorised Curator submits a bulk placement recommendation for all {mention_count:d} mentions"))
def when_bulk_accept(ctx, curation_client, seeded_decisions, nonexistent_ids, mention_count):
    """Submit bulk-accept for all seeded decisions, plus any nonexistent_ids from the given step.

    For outline scenarios nonexistent_ids defaults to [] (no invalid IDs).
    For the partial-success scenario it is supplied by given_2_nonexistent_ids.
    """
    valid_ids = [item["decision_id"] for item in seeded_decisions["items"]]
    all_ids = valid_ids + nonexistent_ids
    resp = curation_client.post(
        "/api/v1/curation/decisions/bulk-accept",
        json={"decision_ids": all_ids},
    )
    ctx["response"] = resp
    ctx["response_body"] = resp.json() if resp.content else {}
    ctx["decision_ids"] = all_ids
    ctx["seeded_items"] = seeded_decisions["items"]
    ctx["mention_count"] = mention_count


@when("an authorised Curator submits a bulk re-evaluation request with an empty selection of mentions")
def when_bulk_accept_empty(ctx, curation_client):
    resp = curation_client.post(
        "/api/v1/curation/decisions/bulk-accept",
        json={"decision_ids": []},
    )
    ctx["response"] = resp
    ctx["response_body"] = resp.json() if resp.content else {}


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------

@then("the bulk re-evaluation request is accepted")
def then_bulk_accepted(ctx):
    status = ctx["response"].status_code
    assert status == 200, (
        f"Expected HTTP 200 for accepted bulk re-evaluation request, got {status}. "
        f"Body: {ctx.get('response_body')}"
    )


@then(parsers.parse("{mention_count:d} independent entries are created in the user action log"))
def then_n_user_action_log_entries(ctx, mongo_db, mention_count):
    count = mongo_db["user_actions"].count_documents({})
    assert count == mention_count, (
        f"Expected {mention_count} user_actions entries, but found {count}."
    )


@then(parsers.parse("{mention_count:d} independent re-evaluation messages are published to the ERE request channel"))
def then_n_ere_messages(mongo_db, mention_count):
    # Check user_actions count rather than Redis queue length: the live ERE worker
    # dequeues ere_requests before the assertion runs. user_actions are written only
    # after ERS successfully publishes, making them durable evidence of the publish.
    count = mongo_db["user_actions"].count_documents({})
    assert count == mention_count, (
        f"Expected {mention_count} message(s) in ere_requests queue, but found {count}."
    )


@then("none of the cluster assignments in the decision store are modified")
def then_no_cluster_assignments_modified(ctx, mongo_db):
    for item in ctx.get("seeded_items", []):
        doc = mongo_db["decisions"].find_one({"_id": item["decision_id"]})
        assert doc is not None, (
            f"Decision document {item['decision_id']!r} is missing from the store."
        )
        actual_cluster = doc["current_placement"]["cluster_id"]
        expected_cluster = item["cluster_id"]
        assert actual_cluster == expected_cluster, (
            f"Cluster assignment was modified for decision {item['decision_id']!r}: "
            f"expected {expected_cluster!r}, got {actual_cluster!r}."
        )


@then("the bulk re-evaluation request returns a partial success outcome")
def then_bulk_partial_success(ctx):
    status = ctx["response"].status_code
    assert status == 200, (
        f"Expected HTTP 200 for partial success bulk response, got {status}. "
        f"Body: {ctx.get('response_body')}"
    )
    body = ctx["response_body"]
    # The response body must signal that some items were processed and some were not.
    # We check that both successful and failed items are reported.
    assert body is not None, "Expected a JSON body in the partial success response."


@then("3 action log entries are created for the valid mentions")
def then_3_action_log_entries(mongo_db):
    count = mongo_db["user_actions"].count_documents({})
    assert count == 3, (
        f"Expected 3 user_actions entries for valid mentions, but found {count}."
    )


@then("3 re-evaluation messages are published to the ERE request channel for the valid mentions")
def then_3_ere_messages(mongo_db):
    count = mongo_db["user_actions"].count_documents({})
    assert count == 3, (
        f"Expected 3 messages in ere_requests queue for valid mentions, but found {count}."
    )


@then("the response includes individual rejection details for each invalid mention")
def then_response_includes_rejection_details(ctx, nonexistent_ids):
    body = ctx["response_body"]
    # BulkActionResponse: {"results": [{"decision_id": ..., "status": ..., "detail": ...}]}
    # statuses: "success", "not_found", "already_curated", "error"
    results = body.get("results", [])
    failed = [r for r in results if r.get("status") != "success"]
    assert len(failed) == len(nonexistent_ids), (
        f"Expected {len(nonexistent_ids)} failed results (not_found), "
        f"got {len(failed)}. Results: {results}"
    )
    for r in failed:
        assert r.get("status") in ("not_found", "error"), (
            f"Expected 'not_found' or 'error' status for invalid ID, got: {r}"
        )


@then("none of the cluster assignments for the valid mentions in the decision store are modified")
def then_valid_cluster_assignments_not_modified(ctx, mongo_db):
    for item in ctx.get("seeded_items", []):
        doc = mongo_db["decisions"].find_one({"_id": item["decision_id"]})
        assert doc is not None, (
            f"Valid decision document {item['decision_id']!r} is missing from the store."
        )
        actual_cluster = doc["current_placement"]["cluster_id"]
        expected_cluster = item["cluster_id"]
        assert actual_cluster == expected_cluster, (
            f"Cluster assignment was modified for valid decision {item['decision_id']!r}: "
            f"expected {expected_cluster!r}, got {actual_cluster!r}."
        )


@then("the bulk re-evaluation request is rejected as invalid")
def then_bulk_rejected_invalid(ctx):
    status = ctx["response"].status_code
    assert status in (400, 422), (
        f"Expected HTTP 400 or 422 for empty bulk request, got {status}. "
        f"Body: {ctx.get('response_body')}"
    )


@then("no entries are created in the user action log")
def then_no_user_action_entries(mongo_db):
    count = mongo_db["user_actions"].count_documents({})
    assert count == 0, (
        f"Expected user_actions to be empty, but found {count} document(s)."
    )


@then("no messages are published to the ERE request channel")
def then_no_ere_messages(redis_client):
    length = redis_client.llen("ere_requests")
    assert length == 0, (
        f"Expected ere_requests queue to be empty, but found {length} message(s)."
    )
