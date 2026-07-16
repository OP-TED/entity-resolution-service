"""Curation API boundary suite — fixtures for authenticated curation operations.

Endpoint reference (port 8000):
  POST /api/v1/curation/decisions/{id}/assign         body: {"cluster_id": str}  → 204
  POST /api/v1/curation/decisions/{id}/accept         no body                    → 204
  POST /api/v1/curation/decisions/{id}/reject         no body                    → 204
  POST /api/v1/curation/decisions/bulk-accept         {"decision_ids": [...]}    → 200
  POST /api/v1/curation/decisions/bulk-reject         {"decision_ids": [...]}    → 200
  GET  /api/v1/curation/decisions                     ?entity_type=&limit=&...   → 200
  GET  /api/v1/curation/stats                         ?entity_type=&...          → 200
  POST /api/v1/users                                  create user (admin only)   → 201
  PATCH /api/v1/users/{id}                            update flags (admin only)  → 200

MongoDB collections (direct access for assertions):
  decisions:    _id=SHA256(triad), about_entity_mention={source_id, request_id, entity_type}
  user_actions: _id=UUID, about_entity_mention={source_id, request_id, entity_type}
  resolution_requests: _id="src::req::type"
"""
import datetime as dt
import hashlib
import uuid

import pytest

from test.ersys.e2e.conftest import derive_provisional_id

# ---------------------------------------------------------------------------
# Test account constants
# ---------------------------------------------------------------------------

TEST_CURATOR_EMAIL = "test-curator@example.com"
TEST_CURATOR_PASSWORD = "TestPass123!"


# ---------------------------------------------------------------------------
# MongoDB document builders — for direct state injection
# ---------------------------------------------------------------------------

def _make_decision_doc(
    source_id: str,
    request_id: str,
    entity_type: str,
    cluster_id: str | None = None,
    confidence_score: float = 0.85,
    similarity_score: float = 0.80,
    extra_candidates: list[dict] | None = None,
) -> dict:
    """Build a decision document for direct MongoDB injection.

    The decisions collection uses SHA-256(triad) as _id.
    `about_entity_mention` is stored flat (no nested `identified_by`).
    `cluster_id` defaults to a fresh UUID to simulate an ERE assignment.
    The cluster_id is always included in `candidates` so /assign can accept it.
    """
    doc_id = derive_provisional_id(source_id, request_id, entity_type)
    effective_cluster = cluster_id or str(uuid.uuid4())
    now = dt.datetime.now(dt.UTC)
    candidates = [
        {
            "cluster_id": effective_cluster,
            "confidence_score": confidence_score,
            "similarity_score": similarity_score,
        }
    ]
    if extra_candidates:
        candidates.extend(extra_candidates)
    return {
        "_id": doc_id,
        "id": doc_id,
        "about_entity_mention": {
            "source_id": source_id,
            "request_id": request_id,
            "entity_type": entity_type,
        },
        "current_placement": {
            "cluster_id": effective_cluster,
            "confidence_score": confidence_score,
            "similarity_score": similarity_score,
        },
        "candidates": candidates,
        "created_at": now,
        "updated_at": None,
        "previous_review_count": 0,
        "reviewed_since_placement": False,
    }


def _make_registry_doc(
    source_id: str,
    request_id: str,
    entity_type: str,
    received_at: dt.datetime | None = None,
) -> dict:
    """Build a resolution_requests record for MongoDB injection."""
    now = received_at or dt.datetime.now(dt.UTC)
    return {
        "_id": f"{source_id}::{request_id}::{entity_type}",
        "identifiedBy": {
            "source_id": source_id,
            "request_id": request_id,
            "entity_type": entity_type,
        },
        "content": "stub content for curation test",
        "content_type": "text/turtle",
        "content_hash": hashlib.sha256(b"stub content for curation test").hexdigest(),
        "received_at": now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
    }


# ---------------------------------------------------------------------------
# Single-decision fixture — user_reevaluation scenarios
# ---------------------------------------------------------------------------

@pytest.fixture
def decision_in_store(mongo_db) -> dict:
    """Inject one canonical decision into MongoDB and return its metadata.

    Returns:
        dict with keys:
          decision_id  — SHA-256 _id used in curation API endpoint paths
          triad        — {source_id, request_id, entity_type}
          cluster_id   — the current_placement cluster_id (also in candidates)
    """
    source_id = "curation-src-001"
    request_id = "curation-req-001"
    entity_type = "ORGANISATION"
    cluster_id = str(uuid.uuid4())

    doc = _make_decision_doc(source_id, request_id, entity_type, cluster_id=cluster_id)
    mongo_db["decisions"].insert_one(doc)
    mongo_db["resolution_requests"].insert_one(
        _make_registry_doc(source_id, request_id, entity_type)
    )
    return {
        "decision_id": doc["_id"],
        "triad": {"source_id": source_id, "request_id": request_id, "entity_type": entity_type},
        "cluster_id": cluster_id,
    }


# ---------------------------------------------------------------------------
# Multi-decision factory — bulk and statistics scenarios
# ---------------------------------------------------------------------------

@pytest.fixture
def decisions_in_store(mongo_db):
    """Factory fixture: inject N decisions into MongoDB.

    Usage::

        def test_something(decisions_in_store):
            items = decisions_in_store(n=3, entity_type="ORGANISATION")
            # items is a list of dicts: {decision_id, triad, cluster_id}

    Each decision gets a unique triad and a distinct ERE-assigned cluster_id
    unless `shared_cluster_id` is provided (for multi-mention / same-cluster tests).
    """
    def _create(
        n: int,
        entity_type: str = "ORGANISATION",
        shared_cluster_id: str | None = None,
    ) -> list[dict]:
        results = []
        for i in range(n):
            src = f"curation-bulk-src-{i:03d}"
            req = f"curation-bulk-req-{i:03d}"
            cluster = shared_cluster_id or str(uuid.uuid4())
            doc = _make_decision_doc(src, req, entity_type, cluster_id=cluster)
            mongo_db["decisions"].insert_one(doc)
            mongo_db["resolution_requests"].insert_one(
                _make_registry_doc(src, req, entity_type)
            )
            results.append({
                "decision_id": doc["_id"],
                "triad": {"source_id": src, "request_id": req, "entity_type": entity_type},
                "cluster_id": cluster,
            })
        return results

    return _create


# ---------------------------------------------------------------------------
# Statistics seeding helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def seed_decisions_and_requests(mongo_db):
    """Factory: seed decisions and registry records for statistics scenarios.

    Usage::

        seed_decisions_and_requests(
            mention_count=10,
            entity_type="ORGANISATION",
            cluster_count=4,
            recent_request_count=3,
        )

    `cluster_count` controls how many distinct cluster_ids are distributed
    across the mentions (round-robin).  `recent_request_count` controls how
    many registry records have a `received_at` within the last 24 hours.
    """
    def _seed(
        mention_count: int,
        entity_type: str,
        cluster_count: int,
        recent_request_count: int,
    ) -> None:
        cluster_ids = [str(uuid.uuid4()) for _ in range(cluster_count)]
        now = dt.datetime.now(dt.UTC)
        old_ts = now - dt.timedelta(days=7)

        for i in range(mention_count):
            src = f"stats-src-{i:04d}"
            req = f"stats-req-{i:04d}"
            cluster = cluster_ids[i % cluster_count]
            doc = _make_decision_doc(src, req, entity_type, cluster_id=cluster)
            mongo_db["decisions"].insert_one(doc)

            received = now if i < recent_request_count else old_ts
            mongo_db["resolution_requests"].insert_one(
                _make_registry_doc(src, req, entity_type, received_at=received)
            )

    return _seed


# ---------------------------------------------------------------------------
# Access management fixtures — manage_access scenarios
# ---------------------------------------------------------------------------

def find_user_by_email(curation_client, email: str) -> dict | None:
    """Search all users via GET /api/v1/users and return the matching record or None.

    The API does not expose GET /api/v1/users/{id}, so we page through the full
    user list and match by email.
    """
    page = 1
    while True:
        resp = curation_client.get("/api/v1/users", params={"page": page, "per_page": 50})
        if resp.status_code != 200:
            return None
        body = resp.json()
        items = body.get("items", [])
        for user in items:
            if user.get("email") == email:
                return user
        total = body.get("total", 0)
        if page * 50 >= total:
            break
        page += 1
    return None


def retire_test_curator_if_exists(curation_client) -> None:
    """Retire (deactivate) the test curator if they exist in the user registry.

    User accounts live in Postgres and are NOT cleared by clean_state (MongoDB-only).
    This function ensures manage_access scenarios start from a clean user state.
    Retiring sets is_active=False so attempts to re-create will not conflict.
    """
    user = find_user_by_email(curation_client, TEST_CURATOR_EMAIL)
    if user is None:
        return
    user_id = user["id"]
    # Retire: deactivate and unverify so the account is effectively gone.
    curation_client.patch(
        f"/api/v1/users/{user_id}",
        json={"is_active": False, "is_verified": False},
    )


@pytest.fixture
def new_curator_payload() -> dict:
    """POST /api/v1/users body to create a test curator account.

    Fields match the UserCreate Pydantic model used by the Curation API.
    `is_verified=True` is required for the curator to perform curation actions.
    """
    return {
        "email": TEST_CURATOR_EMAIL,
        "password": TEST_CURATOR_PASSWORD,
        "is_active": True,
        "is_superuser": False,
        "is_verified": True,
    }


@pytest.fixture
def curator_login_credentials() -> dict:
    """POST /api/v1/auth/login body for the test curator account."""
    return {
        "email": TEST_CURATOR_EMAIL,
        "password": TEST_CURATOR_PASSWORD,
    }
