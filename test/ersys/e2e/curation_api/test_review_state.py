"""Step definitions for curation_api/review_state.feature.

Tests the reviewed_since_placement lifecycle (TEDSWS-524-2):
  1. Fresh ERE placement -> decision is unreviewed (flag starts False)
  2. Curator accept    -> decision removed from unreviewed list (flag flips True)
  3. ERE re-placement  -> decision re-surfaces as unreviewed (flag resets False)

ERE responses are injected directly into the ere_responses Redis list to make
the tests deterministic and independent of live ERE processing latency.
Background steps (health checks, clean state) are shared from
test/ersys/e2e/conftest.py.
"""
import json
import uuid
from datetime import UTC, datetime

import pytest
from pytest_bdd import given, scenarios, then, when

from test.ersys.e2e.conftest import poll_until

scenarios("review_state.feature")


# ---------------------------------------------------------------------------
# Shared context fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Mutable dict shared across steps within one scenario."""
    return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ere_response(triad: dict, cluster_id: str) -> dict:
    """Build a minimal valid ERE response for the given triad."""
    return {
        "@type": "EntityMentionResolutionResponse",
        "ere_request_id": str(uuid.uuid4()),
        "entity_mention_id": triad,
        "candidates": [
            {"cluster_id": cluster_id, "confidence_score": 0.95, "similarity_score": 0.92},
            {"cluster_id": str(uuid.uuid4()), "confidence_score": 0.75, "similarity_score": 0.70},
        ],
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _submit_and_place(
    ers_client,
    redis_client,
    mongo_db,
    triad: dict,
    content: str,
    cluster_id: str,
) -> None:
    """Submit a mention, inject an ERE outcome, poll until the decision is stored."""
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
    doc_id = f"{triad['source_id']}::{triad['request_id']}::{triad['entity_type']}"
    poll_until(
        lambda: mongo_db["resolution_requests"].find_one({"_id": doc_id}),
        timeout_s=15.0,
    )
    redis_client.rpush("ere_responses", json.dumps(_make_ere_response(triad, cluster_id)))

    def _has_cluster():
        doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
        if not doc:
            return None
        return doc if doc.get("current_placement", {}).get("cluster_id") == cluster_id else None

    poll_until(_has_cluster, timeout_s=30.0)


def _poll_reviewed_flag(
    mongo_db, triad: dict, expected: bool, timeout_s: float = 20.0
):
    """Poll until the reviewed_since_placement field equals expected, return the doc."""
    def _check():
        doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
        if not doc:
            return None
        return doc if doc.get("reviewed_since_placement") == expected else None

    return poll_until(_check, timeout_s=timeout_s)


def _list_unreviewed(curation_client) -> list[dict]:
    """GET /api/v1/curation/decisions?reviewed_since_placement=false, return results."""
    resp = curation_client.get(
        "/api/v1/curation/decisions",
        params={"reviewed_since_placement": "false"},
    )
    assert resp.status_code == 200, (
        f"GET decisions?reviewed_since_placement=false failed: "
        f"{resp.status_code} {resp.text}"
    )
    return resp.json().get("results", [])


# ---------------------------------------------------------------------------
# Shared Given — used by all three scenarios
# ---------------------------------------------------------------------------


@given("an entity mention has been submitted and placed by ERE with a known cluster assignment")
def entity_mention_submitted_and_placed(ctx, ers_client, redis_client, mongo_db, org_group1_file1):
    """Submit a mention via ERS, inject an ERE outcome, wait for the decision to land."""
    triad = {
        "source_id": "review-state-src-001",
        "request_id": f"review-state-req-{uuid.uuid4().hex[:8]}",
        "entity_type": "ORGANISATION",
    }
    cluster_id = str(uuid.uuid4())
    _submit_and_place(ers_client, redis_client, mongo_db, triad, org_group1_file1, cluster_id)
    ctx["triad"] = triad
    ctx["cluster_id"] = cluster_id
    doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
    ctx["decision_id"] = doc["_id"]


# ---------------------------------------------------------------------------
# Scenario 1 — fresh placement appears in the unreviewed list
# ---------------------------------------------------------------------------


@when("an authorised Curator queries the list of decisions not yet reviewed since placement")
def curator_queries_unreviewed_list(ctx, curation_client):
    ctx["unreviewed_results"] = _list_unreviewed(curation_client)


@then("that decision appears in the results")
def decision_appears_in_results(ctx):
    decision_id = ctx["decision_id"]
    ids = [item.get("id") for item in ctx["unreviewed_results"]]
    assert decision_id in ids, (
        f"Expected decision {decision_id!r} in unreviewed list, got: {ids}"
    )


# ---------------------------------------------------------------------------
# Scenario 2 — curation removes the decision from the unreviewed list
# ---------------------------------------------------------------------------


@when("an authorised Curator curates that decision")
def curator_curates_decision(ctx, curation_client, mongo_db):
    """Accept the current placement — this atomically sets reviewed_since_placement=True."""
    decision_id = ctx["decision_id"]
    resp = curation_client.post(f"/api/v1/curation/decisions/{decision_id}/accept")
    assert resp.status_code == 204, (
        f"accept failed: {resp.status_code} {resp.text}"
    )
    _poll_reviewed_flag(mongo_db, ctx["triad"], expected=True, timeout_s=20.0)


@then("the decision does not appear in the unreviewed-since-placement list")
def decision_absent_from_unreviewed_list(ctx, curation_client):
    ids = [item.get("id") for item in _list_unreviewed(curation_client)]
    assert ctx["decision_id"] not in ids, (
        f"Decision {ctx['decision_id']!r} should be absent from unreviewed list "
        f"after curation, but was still found: {ids}"
    )


# ---------------------------------------------------------------------------
# Scenario 3 — ERE re-placement resets reviewed_since_placement to False
# ---------------------------------------------------------------------------


@given("an authorised Curator has already curated that decision")
def curator_has_already_curated(ctx, curation_client, mongo_db):
    """Accept the decision so that reviewed_since_placement becomes True."""
    decision_id = ctx["decision_id"]
    resp = curation_client.post(f"/api/v1/curation/decisions/{decision_id}/accept")
    assert resp.status_code == 204, (
        f"accept failed: {resp.status_code} {resp.text}"
    )
    _poll_reviewed_flag(mongo_db, ctx["triad"], expected=True, timeout_s=20.0)


@when("ERE issues a new placement for that mention with a different cluster")
def ere_issues_new_placement(ctx, redis_client, mongo_db):
    """Inject a new ERE response with a distinct cluster_id to trigger a re-placement."""
    triad = ctx["triad"]
    new_cluster_id = str(uuid.uuid4())
    while new_cluster_id == ctx["cluster_id"]:
        new_cluster_id = str(uuid.uuid4())
    redis_client.rpush("ere_responses", json.dumps(_make_ere_response(triad, new_cluster_id)))
    ctx["new_cluster_id"] = new_cluster_id

    def _placement_updated():
        doc = mongo_db["decisions"].find_one({"about_entity_mention": triad})
        if not doc:
            return None
        return doc if doc.get("current_placement", {}).get("cluster_id") == new_cluster_id else None

    poll_until(_placement_updated, timeout_s=30.0)


@then("the decision re-appears in the unreviewed-since-placement list")
def decision_reappears_in_unreviewed_list(ctx, curation_client, mongo_db):
    """Verify reviewed_since_placement was reset, then confirm the API lists the decision."""
    _poll_reviewed_flag(mongo_db, ctx["triad"], expected=False, timeout_s=20.0)
    ids = [item.get("id") for item in _list_unreviewed(curation_client)]
    assert ctx["decision_id"] in ids, (
        f"Expected decision {ctx['decision_id']!r} to re-appear in unreviewed list "
        f"after ERE re-placement, but it was not found: {ids}"
    )


@then("the previous review count for that decision is greater than zero")
def previous_review_count_is_greater_than_zero(ctx, mongo_db):
    doc = mongo_db["decisions"].find_one({"about_entity_mention": ctx["triad"]})
    assert doc is not None, f"No decision found for triad {ctx['triad']}"
    count = doc.get("previous_review_count", 0)
    assert count > 0, (
        f"Expected previous_review_count > 0 after curation, but got {count}. "
        f"Decision doc: {doc}"
    )
