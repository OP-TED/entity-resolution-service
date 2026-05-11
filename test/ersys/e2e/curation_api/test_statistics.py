"""Step definitions for tests/e2e/curation_api/statistics.feature.

UC-W4 — Consult Resolution Statistics.

Implements:
  - Aggregated stats for a known entity type match seeded state (scenario outline)
  - Zero counts when no data exists (scenario)
  - Statistics retrieval is strictly read-only (scenario)
"""
import pytest
from pytest_bdd import given, parsers, scenario, then, when


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------

@scenario(
    "statistics.feature",
    "Aggregated statistics for a known entity type match the seeded state",
)
def test_aggregated_stats_match_seeded():
    pass


@scenario(
    "statistics.feature",
    "Statistics for an entity type return zero counts when no data has been recorded",
)
def test_stats_zero_counts():
    pass


@scenario(
    "statistics.feature",
    "Consulting statistics does not alter any system state",
)
def test_stats_read_only():
    pass


# ---------------------------------------------------------------------------
# Shared context fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    """Mutable dict for intra-scenario shared state."""
    return {}


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------

@given(
    parsers.parse(
        'the decision store contains {mention_count:d} entity mentions of type "{entity_type}" across {cluster_count:d} canonical clusters'
    )
)
def given_decisions_seeded(ctx, seed_decisions_and_requests, mention_count, entity_type, cluster_count):
    """Seed mention_count decisions and registry records."""
    seed_decisions_and_requests(
        mention_count=mention_count,
        entity_type=entity_type,
        cluster_count=cluster_count,
        recent_request_count=mention_count,
    )
    ctx["mention_count"] = mention_count
    ctx["entity_type"] = entity_type
    ctx["cluster_count"] = cluster_count


@given(
    parsers.parse(
        "the request registry contains {mention_count:d} resolution requests for that entity type"
    )
)
def given_registry_requests_noted(ctx, mention_count):
    """Records are already seeded by the previous step; this step notes the expected count."""
    ctx["mention_count"] = mention_count


@given("no entity mentions, clusters, or resolution requests exist in the system")
def given_system_is_empty(ctx):
    """clean_state autouse fixture already cleared all collections before this scenario."""
    ctx["mention_count"] = 0
    ctx["entity_type"] = "ORGANISATION"
    ctx["cluster_count"] = 0


@given("the decision store contains a known set of entity mentions and cluster assignments", target_fixture="snapshot_before")
def given_known_decision_set(ctx, seed_decisions_and_requests, mongo_db):
    """Seed a fixed set of decisions and capture the pre-call document snapshots."""
    seed_decisions_and_requests(
        mention_count=5,
        entity_type="ORGANISATION",
        cluster_count=2,
        recent_request_count=2,
    )
    ctx["entity_type"] = "ORGANISATION"
    decisions_before = list(mongo_db["decisions"].find())
    return {"decisions": decisions_before}


@given("the request registry contains a known set of resolution requests")
def given_known_registry_set(snapshot_before, mongo_db):
    """Capture request registry snapshot — decisions already seeded in previous step."""
    requests_before = list(mongo_db["resolution_requests"].find())
    snapshot_before["requests"] = requests_before


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------

@when(parsers.parse('an authorised Curator requests statistics for entity type "{entity_type}"'))
def when_request_stats(ctx, curation_client, entity_type):
    resp = curation_client.get(
        "/api/v1/curation/stats",
        params={"entity_type": entity_type},
    )
    ctx["response"] = resp
    ctx["response_body"] = resp.json() if resp.content else {}
    ctx.setdefault("entity_type", entity_type)


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------

@then("the statistics response is returned successfully")
def then_stats_returned_successfully(ctx):
    status = ctx["response"].status_code
    assert status == 200, (
        f"Expected HTTP 200 from stats endpoint, got {status}. "
        f"Body: {ctx.get('response_body')}"
    )


@then(parsers.parse("the reported total mention count matches {mention_count:d}"))
def then_total_mention_count_matches(ctx, mention_count):
    body = ctx["response_body"]
    registry = body.get("registry", {})
    actual = registry.get("total_entity_mentions")
    assert actual == mention_count, (
        f"Expected registry.total_entity_mentions={mention_count}, got {actual!r}. "
        f"Body: {body}"
    )


@then(parsers.parse("the reported total cluster count matches {cluster_count:d}"))
def then_total_cluster_count_matches(ctx, cluster_count):
    body = ctx["response_body"]
    registry = body.get("registry", {})
    actual = registry.get("total_canonical_entities")
    assert actual == cluster_count, (
        f"Expected registry.total_canonical_entities={cluster_count}, got {actual!r}. "
        f"Body: {body}"
    )


@then(parsers.parse("the reported total resolution request count matches {mention_count:d}"))
def then_total_resolution_request_count_matches(ctx, mention_count):
    """Assert registry.resolution_requests equals mention_count (total requests in store)."""
    body = ctx["response_body"]
    registry = body.get("registry", {})
    actual = registry.get("resolution_requests")
    assert actual == mention_count, (
        f"Expected registry.resolution_requests={mention_count}, got {actual!r}. "
        f"Body: {body}"
    )


@then("the decision store state is not modified by the statistics retrieval")
def then_decision_store_not_modified_by_stats(ctx, mongo_db):
    """Confirm that the GET /stats call did not alter the decisions collection."""
    mention_count = ctx.get("mention_count", 0)
    actual_count = mongo_db["decisions"].count_documents({})
    assert actual_count == mention_count, (
        f"Expected decisions count={mention_count} after stats retrieval, "
        f"got {actual_count}."
    )


@then("all reported counts are zero")
def then_all_counts_zero(ctx):
    body = ctx["response_body"]
    registry = body.get("registry", {})
    curation = body.get("curation", {})

    registry_zero = (
        registry.get("total_entity_mentions") == 0
        and registry.get("total_canonical_entities") == 0
        and registry.get("resolution_requests") == 0
    )
    curation_zero = (
        curation.get("total_decisions") == 0
    )
    assert registry_zero, (
        f"Expected all registry counts to be 0. registry section: {registry}"
    )
    assert curation_zero, (
        f"Expected all curation counts to be 0. curation section: {curation}"
    )


@then("the decision store remains empty")
def then_decision_store_empty_after_stats(mongo_db):
    count = mongo_db["decisions"].count_documents({})
    assert count == 0, (
        f"Expected decisions collection to remain empty after stats call, "
        f"found {count} document(s)."
    )


@then("the decision store contains exactly the same documents as before the call")
def then_decisions_unchanged(snapshot_before, mongo_db):
    docs_after = list(mongo_db["decisions"].find())
    ids_before = {str(d["_id"]) for d in snapshot_before["decisions"]}
    ids_after = {str(d["_id"]) for d in docs_after}
    assert ids_before == ids_after, (
        f"decisions collection changed after stats call. "
        f"Before: {ids_before}. After: {ids_after}."
    )


@then("the request registry contains exactly the same documents as before the call")
def then_registry_unchanged(snapshot_before, mongo_db):
    docs_after = list(mongo_db["resolution_requests"].find())
    ids_before = {str(d["_id"]) for d in snapshot_before["requests"]}
    ids_after = {str(d["_id"]) for d in docs_after}
    assert ids_before == ids_after, (
        f"resolution_requests collection changed after stats call. "
        f"Before: {ids_before}. After: {ids_after}."
    )


@then("no messages are published to the ERE request channel")
def then_no_ere_messages_stats(redis_client):
    length = redis_client.llen("ere_requests")
    assert length == 0, (
        f"Expected ere_requests queue to be empty after stats call, "
        f"but found {length} message(s)."
    )
