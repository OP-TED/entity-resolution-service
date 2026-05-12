"""E2E shared conftest — HTTP clients, state clients, and scenario cleanup.

All e2e suites (full_cycle, ers_api, curation_api, ere_async) inherit these
fixtures. Actions go through HTTP clients; assertions use mongo/redis clients.

Module-level helpers (importable by all suites):
  - build_resolve_payload()    build the correct nested POST /resolve body
  - derive_provisional_id()    SHA-256 draft cluster id for a triad
  - wait_for_canonical()       poll GET /lookup until ERE returns a cluster
"""
import contextlib
import hashlib
import time

import httpx
import pymongo
import pytest
import redis
from pytest_bdd import given

# ---------------------------------------------------------------------------
# Cross-suite helper functions — importable from any suite conftest or test
# ---------------------------------------------------------------------------

def build_resolve_payload(
    source_id: str,
    request_id: str,
    entity_type: str,
    content: str,
    content_type: str = "text/turtle",
) -> dict:
    """Return a correctly-nested POST /api/v1/resolve request body.

    ERS expects: {"mention": {"identifiedBy": {...}, "content": ..., "content_type": ...}}
    """
    return {
        "mention": {
            "identifiedBy": {
                "source_id": source_id,
                "request_id": request_id,
                "entity_type": entity_type,
            },
            "content": content,
            "content_type": content_type,
        }
    }


def derive_provisional_id(source_id: str, request_id: str, entity_type: str) -> str:
    """Return the deterministic provisional cluster ID for a mention triad.

    Mirrors the ERS algorithm: SHA-256 of the concatenated triad fields.
    """
    return hashlib.sha256(
        f"{source_id}{request_id}{entity_type}".encode()
    ).hexdigest()


def wait_for_canonical(ers_client, triad: dict, timeout_s: float = 30.0) -> dict:
    """Poll GET /api/v1/lookup until ERE assigns a canonical cluster.

    Args:
        ers_client: httpx.Client pointed at the ERS API.
        triad: dict with source_id, request_id, entity_type.
        timeout_s: Maximum seconds to wait.

    Returns:
        The lookup response body once cluster_reference.cluster_id is present.

    Raises:
        TimeoutError: If no canonical assignment appears within timeout_s.
    """
    def _check():
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
            return body if body.get("cluster_reference", {}).get("cluster_id") else None
        return None

    return poll_until(_check, timeout_s=timeout_s)


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------

def _require(env: dict, key: str) -> str:
    """Return env[key] or raise clearly if absent."""
    value = env.get(key)
    if not value:
        raise RuntimeError(
            f"Required variable '{key}' is not set in infra/.env. "
            f"Run 'make init' or check infra/.env.example."
        )
    return value


# ---------------------------------------------------------------------------
# HTTP clients
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def ers_api_url(env) -> str:
    return f"http://{_require(env, 'STACK_HOST')}:{_require(env, 'ERS_API_PORT')}"


@pytest.fixture(scope="session")
def curation_api_url(env) -> str:
    return f"http://{_require(env, 'STACK_HOST')}:{_require(env, 'UVICORN_PORT')}"


@pytest.fixture(scope="session")
def ers_client(ers_api_url) -> httpx.Client:
    """Synchronous httpx client for ERS REST API (:8001)."""
    with httpx.Client(base_url=ers_api_url, timeout=60.0) as client:
        yield client


@pytest.fixture(scope="session")
def auth_token(curation_api_url, env) -> str:
    """Obtain a Bearer token from the Curation API login endpoint."""
    login_url = f"{curation_api_url}/api/v1/auth/login"
    payload = {
        "email": _require(env, "ADMIN_EMAIL"),
        "password": _require(env, "ADMIN_PASSWORD"),
    }
    resp = httpx.post(login_url, json=payload, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    # Token location may vary — adjust after schema discovery
    return data.get("access_token") or data.get("token") or data["access_token"]


@pytest.fixture(scope="session")
def curation_client(curation_api_url, auth_token) -> httpx.Client:
    """Authenticated httpx client for Curation API (:8000)."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    with httpx.Client(
        base_url=curation_api_url, headers=headers, timeout=60.0
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# State clients — for assertions and injection
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def mongo_client(env) -> pymongo.MongoClient:
    """pymongo client connected to FerretDB (:27017)."""
    uri = _require(env, "MONGO_URI")
    client = pymongo.MongoClient(uri)
    yield client
    client.close()


@pytest.fixture(scope="session")
def mongo_db(mongo_client, env) -> pymongo.database.Database:
    """The ERS database."""
    db_name = _require(env, "MONGO_DATABASE_NAME")
    return mongo_client[db_name]


@pytest.fixture(scope="session")
def redis_client(env) -> redis.Redis:
    """Synchronous redis client connected to the stack Redis (:6379)."""
    client = redis.Redis(
        host=_require(env, "REDIS_HOST"),
        port=int(_require(env, "REDIS_PORT")),
        password=_require(env, "REDIS_PASSWORD"),
        decode_responses=True,
    )
    yield client
    client.close()


# ---------------------------------------------------------------------------
# Scenario isolation — clean state before each scenario
# ---------------------------------------------------------------------------
# Collection and channel names — TO BE DISCOVERED via GitNexus.
# These are placeholder names following the spec language.
_MONGO_COLLECTIONS_TO_CLEAN: list[str] = [
    "resolution_requests",
    "decisions",
    "user_actions",
    "lookup_states",
]

_REDIS_CHANNELS: list[str] = [
    "ere_requests",
    "ere_responses",
]


@pytest.fixture(autouse=True)
def clean_state(mongo_db, redis_client):
    """Truncate MongoDB collections and flush Redis queues before each scenario.

    Ensures scenario isolation without restarting the stack.
    Runs before (yield) and does nothing after.

    NOTE: Collection names are placeholders — replace after GitNexus discovery.
    """
    for coll_name in _MONGO_COLLECTIONS_TO_CLEAN:
        mongo_db[coll_name].delete_many({})
    for channel in _REDIS_CHANNELS:
        while redis_client.lpop(channel) is not None:
            pass
    yield


# ---------------------------------------------------------------------------
# Polling helper — for async ERE scenarios
# ---------------------------------------------------------------------------
def poll_until(predicate, timeout_s: float = 30.0, interval_s: float = 0.5):
    """Poll predicate() until it returns a truthy value or timeout.

    Args:
        predicate: Callable returning a truthy value on success.
        timeout_s: Maximum wait time in seconds.
        interval_s: Polling interval in seconds.

    Returns:
        The truthy result from predicate().

    Raises:
        TimeoutError: If predicate never returns truthy within timeout.
    """
    deadline = time.monotonic() + timeout_s
    last_result = None
    while time.monotonic() < deadline:
        last_result = predicate()
        if last_result:
            return last_result
        time.sleep(interval_s)
    raise TimeoutError(
        f"poll_until timed out after {timeout_s}s. Last result: {last_result}"
    )


# ---------------------------------------------------------------------------
# Cross-suite resolved_mention fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def resolved_mention(ers_client, resolve_payload):
    """Submit a mention and poll until ERE returns a canonical cluster assignment.

    Requires the calling suite's conftest to define a `resolve_payload` fixture.
    Returns the POST /resolve response body enriched with a 'lookup' key once
    ERE responds.  If ERE times out (e.g. provisional scenario), 'lookup' is
    absent and the test can still inspect the resolve response.
    """
    resp = ers_client.post("/api/v1/resolve", json=resolve_payload)
    resp.raise_for_status()
    data = resp.json()
    triad = resolve_payload["mention"]["identifiedBy"]
    with contextlib.suppress(TimeoutError):
        data["lookup"] = wait_for_canonical(ers_client, triad, timeout_s=30.0)
    return data


# ---------------------------------------------------------------------------
# Shared background steps — used by Background sections across all e2e suites
# Defined here once to avoid duplicate-step errors when suites run together.
# ---------------------------------------------------------------------------


@given("the ERS API is reachable")
def shared_ers_api_is_reachable(ers_client):
    resp = ers_client.get("/health")
    assert resp.status_code == 200, (
        f"ERS API health check failed: {resp.status_code}"
    )


@given("the Curation API is reachable")
def shared_curation_api_is_reachable(curation_client):
    resp = curation_client.get("/health")
    assert resp.status_code == 200, (
        f"Curation API health check failed: {resp.status_code}"
    )


@given("the ERE worker is processing requests")
def shared_ere_worker_is_processing(redis_client):
    assert redis_client.ping(), "Redis is not reachable — ERE cannot process requests"


@given("the request registry is empty")
def shared_request_registry_is_empty(mongo_db):
    mongo_db["resolution_requests"].delete_many({})
    assert mongo_db["resolution_requests"].count_documents({}) == 0


@given("the decision store is empty")
def shared_decision_store_is_empty(mongo_db):
    mongo_db["decisions"].delete_many({})
    assert mongo_db["decisions"].count_documents({}) == 0


@given("the ERE request queue is empty")
def shared_ere_request_queue_is_empty(redis_client):
    while redis_client.lpop("ere_requests") is not None:
        pass
    assert redis_client.llen("ere_requests") == 0


@given("the ERE response channel is operational")
def shared_ere_response_channel_is_operational(redis_client):
    assert redis_client.ping(), "Redis is not reachable — ERE response channel unavailable"


@given("the user action log is empty")
def shared_user_action_log_is_empty(mongo_db):
    mongo_db["user_actions"].delete_many({})
    assert mongo_db["user_actions"].count_documents({}) == 0


@given("the ERE request channel is empty")
def shared_ere_request_channel_is_empty(redis_client):
    while redis_client.lpop("ere_requests") is not None:
        pass
    assert redis_client.llen("ere_requests") == 0


@given("the access registry contains no test curator accounts")
def shared_access_registry_clean(mongo_db):
    """Remove any leftover test curator accounts from previous test runs."""
    mongo_db["users"].delete_many({"email": {"$regex": "^test-curator@"}})
    assert mongo_db["users"].count_documents({"email": {"$regex": "^test-curator@"}}) == 0
