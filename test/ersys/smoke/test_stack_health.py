"""Smoke tests — stack reachability.

Purpose:
  Verify that every service in the ERSys stack is alive and responding before
  running any e2e or integration test suite.  These tests make no business
  assertions and leave no state; they only check that each service returns a
  non-error response to a lightweight probe request.

Usage:
  make test-smoke                  # runs pytest -m smoke -v
  make up && make test-smoke       # typical pre-e2e check

Requires:
  The full Docker Compose stack must be running (make up) and infra/.env must
  exist (make init or cp infra/.env.example infra/.env).
"""
import httpx
import pymongo
import pymongo.errors
import pytest
import redis


def _require(env: dict, key: str) -> str:  # type: ignore[return]
    """Return env[key] or fail clearly if it is absent."""
    value = env.get(key)
    if not value:
        pytest.fail(
            f"Required environment variable '{key}' is not set in infra/.env. "
            f"Run 'make init' or copy infra/.env.example to infra/.env."
        )
    return value


# ---------------------------------------------------------------------------
# HTTP service probes — parametrized so each service is its own test item
# ---------------------------------------------------------------------------

HTTP_PROBES = [
    # (test id, port_env_key, path, expected_status_codes)
    ("curation-api /docs",   "UVICORN_PORT", "/docs",          {200}),
    ("curation-api /health", "UVICORN_PORT", "/api/v1/health", {200, 404}),
    ("ers-api /docs",        "ERS_API_PORT", "/docs",          {200}),
    ("ers-api /health",      "ERS_API_PORT", "/api/v1/health", {200, 404}),
    ("webapp /",             "WEBAPP_PORT",  "/",              {200}),
]


@pytest.mark.parametrize("label,port_key,path,ok_codes", HTTP_PROBES, ids=[p[0] for p in HTTP_PROBES])
def test_http_service_reachable(env, label, port_key, path, ok_codes):
    """Each HTTP service answers a lightweight GET without error."""
    host = _require(env, "STACK_HOST")
    port = _require(env, port_key)
    base_url = f"http://{host}:{port}"
    try:
        resp = httpx.get(f"{base_url}{path}", timeout=10.0, follow_redirects=True)
    except httpx.ConnectError as exc:
        pytest.fail(
            f"[{label}] Cannot connect to {base_url}{path}. "
            f"Is the stack running? (make up)\n{exc}"
        )
    assert resp.status_code in ok_codes, (
        f"[{label}] {base_url}{path} returned HTTP {resp.status_code}; "
        f"expected one of {ok_codes}."
    )


# ---------------------------------------------------------------------------
# Infrastructure probes
# ---------------------------------------------------------------------------

def test_redis_reachable(env):
    """Redis answers PING."""
    client = redis.Redis(
        host=_require(env, "REDIS_HOST"),
        port=int(_require(env, "REDIS_PORT")),
        password=_require(env, "REDIS_PASSWORD"),
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        pong = client.ping()
    except redis.ConnectionError as exc:
        pytest.fail(
            f"Cannot connect to Redis at "
            f"{env.get('REDIS_HOST')}:{env.get('REDIS_PORT')}. "
            f"Is the stack running? (make up)\n{exc}"
        )
    finally:
        client.close()
    assert pong is True, "Redis PING did not return True."


def test_mongodb_reachable(env):
    """FerretDB/MongoDB answers a server ping."""
    mongo_uri = _require(env, "MONGO_URI")
    client: pymongo.MongoClient | None = None
    try:
        client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
    except pymongo.errors.ServerSelectionTimeoutError as exc:
        pytest.fail(
            f"Cannot connect to MongoDB/FerretDB at {mongo_uri}. "
            f"Is the stack running? (make up)\n{exc}"
        )
    finally:
        if client is not None:
            client.close()
