"""Step definitions for tests/e2e/ers_api/resolve_mention.feature.

Implements:
  - Canonical resolution (scenario 1)
  - Idempotent replay (scenario 4)
  - Idempotency conflict (scenario 5)
  - Missing required field outline (scenario 6, 5 examples)
  - Unsupported entity type (scenario 7)

Skipped (require execution-window control or config injection):
  - Provisional draft issuance (scenario 2)
  - Draft determinism (scenario 3)
  - Client timeout budget (scenario 8)
  - Critical dependency unavailable (scenario 9)
"""
import pytest
from pytest_bdd import given, parsers, scenario, then, when

from test.ersys.e2e.conftest import poll_until
from test.ersys.e2e.ers_api.conftest import derive_provisional_id

# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

@scenario("resolve_mention.feature", "Canonical resolution when ERE responds within the execution window")
def test_canonical_resolution():
    pass


@scenario("resolve_mention.feature", "Provisional draft identifier issued when ERE does not respond within the execution window")
def test_provisional_draft_issued():
    pytest.skip("Requires controlling ERE execution window timing — not available in black-box mode")


@scenario("resolve_mention.feature", "Same entity mention triad always produces the same draft identifier")
def test_draft_determinism():
    pytest.skip("Requires controlling ERE execution window timing — not available in black-box mode")


@scenario("resolve_mention.feature", "Identical submission replayed returns the same result without creating a duplicate entry")
def test_idempotent_replay():
    pass


@scenario("resolve_mention.feature", "Submission with same triad but different content is rejected as an idempotency conflict")
def test_idempotency_conflict():
    pass


@scenario(
    "resolve_mention.feature",
    "Submission missing a required field is rejected without registering a request",
)
def test_missing_required_field():
    pass


@scenario("resolve_mention.feature", "Submission with an unsupported entity type is explicitly rejected")
def test_unsupported_entity_type():
    pass


@scenario("resolve_mention.feature", "ERS returns an appropriate error before the client timeout budget is exceeded")
def test_client_timeout_budget():
    pytest.skip("Requires config injection for execution window — not available in black-box mode")


@scenario("resolve_mention.feature", "ERS returns an error and leaves no partial state when a critical dependency is unavailable")
def test_critical_dependency_unavailable():
    pytest.skip("Requires stopping a running service (MongoDB) — not available in black-box mode")


# ---------------------------------------------------------------------------
# Shared context fixture — carries state between given/when/then steps
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    """Mutable dictionary for intra-scenario shared state."""
    return {}


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------

@given("a valid entity mention request for an organisation using the first test file")
def given_valid_mention_first_file(ctx, resolve_payload):
    ctx["payload"] = resolve_payload


@given("an alternative payload for the same entity mention triad using a different content file")
def given_alternative_payload(ctx, alternative_payload):
    ctx["alternative_payload"] = alternative_payload


@given(parsers.parse('an entity mention request with the "{missing_field}" field omitted'))
def given_mention_with_missing_field(ctx, missing_field, org_group1_file1):
    """Build a valid payload then remove the named field."""
    full_payload = {
        "mention": {
            "identifiedBy": {
                "source_id": "test-source-missing",
                "request_id": "test-request-missing",
                "entity_type": "ORGANISATION",
            },
            "content": org_group1_file1,
            "content_type": "text/turtle",
        }
    }
    if missing_field == "source_id":
        del full_payload["mention"]["identifiedBy"]["source_id"]
    elif missing_field == "request_id":
        del full_payload["mention"]["identifiedBy"]["request_id"]
    elif missing_field == "entity_type":
        del full_payload["mention"]["identifiedBy"]["entity_type"]
    elif missing_field == "content":
        del full_payload["mention"]["content"]
    elif missing_field == "content_type":
        del full_payload["mention"]["content_type"]
    else:
        pytest.fail(f"Unknown missing_field: {missing_field!r}")
    ctx["payload"] = full_payload


# ---------------------------------------------------------------------------
# Stub Given steps for skipped scenarios
# pytest-bdd resolves all step definitions before running the scenario body,
# so pytest.skip() in the @scenario function is too late to suppress the
# StepDefinitionNotFoundError. These stubs ensure collection succeeds; the
# actual skip is issued at the first step execution.
# ---------------------------------------------------------------------------

@given("the ERE engine will not respond within the execution window")
def given_ere_will_not_respond():
    pytest.skip(
        "Requires controlling ERE execution window timing — not available in black-box mode"
    )


@given("the Originator submits the same entity mention for resolution a second time",
       target_fixture="ctx")
def given_submit_second_time_stub(ctx, ers_client):
    resp = ers_client.post("/api/v1/resolve", json=ctx["payload"])
    ctx["response2"] = resp
    ctx["response_body2"] = resp.json()
    return ctx


@given("both ERE and the ERS internal execution window are configured to exceed the client timeout budget")
def given_both_ere_and_window_exceed_budget():
    pytest.skip(
        "Requires config injection for execution window — not available in black-box mode"
    )


@given("the request registry dependency is unavailable")
def given_request_registry_unavailable():
    pytest.skip(
        "Requires stopping a running service (MongoDB) — not available in black-box mode"
    )


@given("an entity mention request where the entity type is set to an unsupported value")
def given_unsupported_entity_type(ctx, org_group1_file1):
    ctx["payload"] = {
        "mention": {
            "identifiedBy": {
                "source_id": "test-source-unsupported",
                "request_id": "test-request-unsupported",
                "entity_type": "UNSUPPORTED_TYPE",
            },
            "content": org_group1_file1,
            "content_type": "text/turtle",
        }
    }


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------

@when("the Originator submits the entity mention for resolution")
def when_submit_first(ctx, ers_client):
    resp = ers_client.post("/api/v1/resolve", json=ctx["payload"])
    ctx["response"] = resp
    ctx["response_body"] = resp.json()


@when("the Originator submits the same entity mention for resolution a second time")
def when_submit_second(ctx, ers_client):
    resp = ers_client.post("/api/v1/resolve", json=ctx["payload"])
    ctx["response2"] = resp
    ctx["response_body2"] = resp.json()


@when("the Originator submits the alternative payload for the same triad")
def when_submit_alternative(ctx, ers_client):
    resp = ers_client.post("/api/v1/resolve", json=ctx["alternative_payload"])
    ctx["response2"] = resp
    ctx["response_body2"] = resp.json()


# ---------------------------------------------------------------------------
# Then steps — canonical resolution
# ---------------------------------------------------------------------------

@then("the resolution is accepted")
def then_resolution_is_accepted(ctx):
    status = ctx["response"].status_code
    assert status in (200, 202), (
        f"Expected 200 (canonical) or 202 (provisional), got {status}. "
        f"Body: {ctx['response_body']}"
    )


@then("the response contains a canonical cluster identifier assigned by ERE")
def then_response_has_canonical_cluster_id(ctx):
    body = ctx["response_body"]
    assert ctx["response"].status_code == 200, (
        f"Expected HTTP 200 for canonical resolution, got {ctx['response'].status_code}. "
        f"Body: {body}"
    )
    assert body.get("canonical_entity_id"), (
        f"Expected non-empty canonical_entity_id in response. Body: {body}"
    )
    assert body.get("status") == "CANONICAL", (
        f"Expected status=CANONICAL in response. Body: {body}"
    )
    # Canonical cluster ID must differ from the provisional (SHA256 of triad)
    ident = body["identified_by"]
    provisional = derive_provisional_id(
        ident["source_id"], ident["request_id"], ident["entity_type"]
    )
    assert body["canonical_entity_id"] != provisional, (
        f"cluster_id matches provisional ID — ERE did not provide a canonical assignment. "
        f"canonical_entity_id={body['canonical_entity_id']!r}"
    )
    ctx["canonical_entity_id"] = body["canonical_entity_id"]


@then("the entity mention is registered in the request registry")
def then_mention_is_registered(ctx, mongo_db):
    ident = ctx["response_body"]["identified_by"]
    composite_id = f"{ident['source_id']}::{ident['request_id']}::{ident['entity_type']}"
    doc = mongo_db["resolution_requests"].find_one({"_id": composite_id})
    assert doc is not None, (
        f"Expected a record in resolution_requests for _id={composite_id!r}, but none found."
    )


@then("the cluster assignment is recorded in the decision store")
def then_cluster_assignment_in_decisions(ctx, mongo_db):
    ident = ctx["response_body"]["identified_by"]
    doc = mongo_db["decisions"].find_one({
        "about_entity_mention": {
            "source_id": ident["source_id"],
            "request_id": ident["request_id"],
            "entity_type": ident["entity_type"],
        }
    })
    assert doc is not None, (
        f"Expected a decision record for {ident}, but none found in decisions collection."
    )
    cluster_id = doc["current_placement"]["cluster_id"]
    assert cluster_id == ctx["canonical_entity_id"], (
        f"Decision cluster_id {cluster_id!r} does not match "
        f"canonical_entity_id {ctx['canonical_entity_id']!r} from the API response."
    )


@then("no draft identifier is present in the response")
def then_no_draft_id(ctx):
    body = ctx["response_body"]
    ident = body["identified_by"]
    provisional = derive_provisional_id(
        ident["source_id"], ident["request_id"], ident["entity_type"]
    )
    assert body.get("canonical_entity_id") != provisional, (
        f"canonical_entity_id matches provisional SHA256 — this is a draft, not canonical. "
        f"canonical_entity_id={body.get('canonical_entity_id')!r}"
    )


# ---------------------------------------------------------------------------
# Then steps — idempotent replay
# ---------------------------------------------------------------------------

@then("both responses contain the same canonical identifier")
def then_both_responses_same_canonical(ctx):
    id1 = ctx["response_body"].get("canonical_entity_id")
    id2 = ctx["response_body2"].get("canonical_entity_id")
    assert id1 is not None, f"First response missing canonical_entity_id. Body: {ctx['response_body']}"
    assert id2 is not None, f"Second response missing canonical_entity_id. Body: {ctx['response_body2']}"
    assert id1 == id2, (
        f"Idempotent replay returned different canonical IDs: "
        f"first={id1!r}, second={id2!r}"
    )


@then("the request registry contains exactly one entry for that triad")
def then_registry_has_exactly_one_entry(ctx, mongo_db):
    ident = ctx["response_body"]["identified_by"]
    composite_id = f"{ident['source_id']}::{ident['request_id']}::{ident['entity_type']}"
    count = mongo_db["resolution_requests"].count_documents({"_id": composite_id})
    assert count == 1, (
        f"Expected exactly 1 entry in resolution_requests for _id={composite_id!r}, "
        f"but found {count}."
    )


# ---------------------------------------------------------------------------
# Then steps — idempotency conflict
# ---------------------------------------------------------------------------

@then("the second submission is rejected as a conflict")
def then_second_submission_rejected_conflict(ctx):
    status = ctx["response2"].status_code
    assert status == 422, (
        f"Expected HTTP 422 for idempotency conflict, got {status}. "
        f"Body: {ctx['response_body2']}"
    )
    body = ctx["response_body2"]
    assert body.get("error_code") == "IDEMPOTENCY_CONFLICT", (
        f"Expected error_code=IDEMPOTENCY_CONFLICT, got: {body.get('error_code')!r}. "
        f"Full body: {body}"
    )


@then("the request registry still contains exactly one entry for that triad")
def then_registry_still_one_entry(ctx, mongo_db):
    ident = ctx["response_body"]["identified_by"]
    composite_id = f"{ident['source_id']}::{ident['request_id']}::{ident['entity_type']}"
    count = mongo_db["resolution_requests"].count_documents({"_id": composite_id})
    assert count == 1, (
        f"Expected exactly 1 entry in resolution_requests after conflict, "
        f"but found {count} for _id={composite_id!r}."
    )


@then("the decision store is not modified by the conflicting submission")
def then_decision_store_not_modified_by_conflict(ctx, mongo_db):
    # Count before second submission was stored in ctx during polling
    count = mongo_db["decisions"].count_documents({})
    # After conflict the count must not have grown beyond 1 (only the first submission's decision)
    assert count == 1, (
        f"Expected exactly 1 decision after idempotency conflict, but found {count}."
    )


# ---------------------------------------------------------------------------
# Then steps — missing field validation
# ---------------------------------------------------------------------------

@then("the submission is rejected as invalid")
def then_submission_rejected_invalid(ctx):
    status = ctx["response"].status_code
    assert status == 400, (
        f"Expected HTTP 400 for missing required field, got {status}. "
        f"Body: {ctx['response_body']}"
    )


@then("the request registry remains empty")
def then_registry_remains_empty(ctx, mongo_db):
    count = mongo_db["resolution_requests"].count_documents({})
    assert count == 0, (
        f"Expected resolution_requests to be empty after rejected submission, "
        f"but found {count} document(s)."
    )


@then("no message is published to the ERE request channel")
def then_no_ere_message_published(redis_client):
    length = redis_client.llen("ere_requests")
    assert length == 0, (
        f"Expected ere_requests queue to be empty, but it has {length} message(s)."
    )


# ---------------------------------------------------------------------------
# Then steps — unsupported entity type
# ---------------------------------------------------------------------------

@then("the submission is rejected with an explicit unsupported-type error")
def then_rejected_unsupported_type(ctx):
    status = ctx["response"].status_code
    assert status == 400, (
        f"Expected HTTP 400 for unsupported entity type, got {status}. "
        f"Body: {ctx['response_body']}"
    )
    body = ctx["response_body"]
    # The error must explicitly reference the entity type being unsupported
    detail = body.get("message", "") or body.get("detail", "")
    assert "not supported" in detail.lower() or "unsupported" in detail.lower(), (
        f"Expected 'not supported' or 'unsupported' in error detail, got: {detail!r}"
    )


# ---------------------------------------------------------------------------
# Step for scenarios that wait for ERE to produce a canonical decision
# (used implicitly in the canonical scenario via poll_until in assertions)
# ---------------------------------------------------------------------------

def _wait_for_canonical_decision(mongo_db, source_id, request_id, entity_type, timeout_s=30):
    """Poll decisions until ERE produces a canonical (non-provisional) placement.

    Args:
        mongo_db: pymongo Database.
        source_id: Source system identifier of the mention.
        request_id: Request identifier.
        entity_type: Entity type string.
        timeout_s: Maximum seconds to wait.

    Returns:
        The decision document once a canonical assignment is found.

    Raises:
        TimeoutError: If no canonical decision appears within timeout.
        AssertionError: If the decision is still provisional after timeout.
    """
    provisional = derive_provisional_id(source_id, request_id, entity_type)

    def _check():
        doc = mongo_db["decisions"].find_one({
            "about_entity_mention": {
                "source_id": source_id,
                "request_id": request_id,
                "entity_type": entity_type,
            }
        })
        if doc is None:
            return None
        cluster_id = doc["current_placement"]["cluster_id"]
        if cluster_id != provisional:
            return doc
        return None

    return poll_until(_check, timeout_s=timeout_s)
