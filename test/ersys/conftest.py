"""Root ersys conftest — env loading, test-type markers, and test data fixtures.

All ersys e2e and smoke tests inherit from this conftest.

Environment variables:
    ERS_ENV_FILE:   path to ers repo's env file (default: src/infra/.env)
    ERE_ENV_FILE:   path to ere repo's env file (optional)
    WEBAPP_ENV_FILE: path to webapp repo's env file (optional)
"""
import json
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
TESTS_ROOT_DIR = Path(__file__).parent
TEST_DATA_DIR = TESTS_ROOT_DIR / "test_data"

# ---------------------------------------------------------------------------
# Environment — merged from component repo env files
# ---------------------------------------------------------------------------
def _load_env() -> dict[str, str | None]:
    """Merge env files from component repos.

    Load order: ERE → WEBAPP → ERS (ERS values win on conflict).
    ERS_ENV_FILE defaults to src/infra/.env relative to the ers repo root.
    ERE_ENV_FILE and WEBAPP_ENV_FILE are optional.

    Defaults injected when not present in any env file:
      STACK_HOST=localhost  — hostname used to reach all stack ports from the host
      WEBAPP_PORT=8080      — webapp port (not exported by webapp .env.example)

    Note: REDIS_HOST in ers .env.example is set to the Docker service name
    (ersys-redis).  When running tests from the host machine, override it to
    localhost in your local src/infra/.env copy.
    """
    repo_root = Path(__file__).parent.parent.parent  # test/ersys -> test -> repo root
    default_ers_env = repo_root / "src" / "infra" / ".env"

    merged: dict[str, str | None] = {}
    for env_var, default in [
        ("ERE_ENV_FILE", None),
        ("WEBAPP_ENV_FILE", None),
        ("ERS_ENV_FILE", default_ers_env),  # loaded last — ERS values win on conflict
    ]:
        raw = os.environ.get(env_var)
        path = Path(raw) if raw else default
        if path and Path(path).exists():
            merged.update(dotenv_values(path))

    # Fallback defaults for variables not exported by any component .env.example
    merged.setdefault("STACK_HOST", "localhost")
    merged.setdefault("WEBAPP_PORT", "8080")

    # Shell env vars take highest priority — lets callers override Docker-internal
    # hostnames (e.g. REDIS_HOST=localhost, MONGO_URI=...@localhost:...) without
    # touching the .env file that Docker Compose also reads.
    merged.update({k: v for k, v in os.environ.items() if k in merged})

    return merged


_ENV = _load_env()


@pytest.fixture(scope="session")
def env() -> dict[str, str | None]:
    """Merged key-value pairs from component repo env files."""
    return dict(_ENV)


# ---------------------------------------------------------------------------
# Marker hook — auto-apply markers by directory
# ---------------------------------------------------------------------------
def pytest_collection_modifyitems(items: list) -> None:
    """Apply test-type markers based on directory location.

    pytest ignores ``pytestmark`` in conftest.py (loaded as plugin, not test
    module). This hook stamps every collected item so that ``-m e2e`` etc.
    filter correctly.
    """
    for item in items:
        path = str(item.fspath)
        if "/test/ersys/e2e/" in path:
            item.add_marker(pytest.mark.e2e)
        elif "/test/ersys/smoke/" in path:
            item.add_marker(pytest.mark.ersys_smoke)


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------
def load_text_file(relative_path: str) -> str:
    """Load text content from the test_data directory."""
    file_path = TEST_DATA_DIR / relative_path
    if not file_path.exists():
        raise FileNotFoundError(f"Test data file not found: {file_path}")
    return file_path.read_text(encoding="utf-8")


def load_json_file(relative_path: str) -> dict:
    """Load and parse JSON from the test_data directory."""
    file_path = TEST_DATA_DIR / relative_path
    if not file_path.exists():
        raise FileNotFoundError(f"Test data file not found: {file_path}")
    return json.loads(file_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Session-scoped test data fixtures — Organizations group1
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def org_group1_file1() -> str:
    return load_text_file("organizations/group1/661238-2023.ttl")


@pytest.fixture(scope="session")
def org_group1_file2() -> str:
    return load_text_file("organizations/group1/662860-2023.ttl")


@pytest.fixture(scope="session")
def org_group1_file3() -> str:
    return load_text_file("organizations/group1/663653-2023.ttl")


# ---------------------------------------------------------------------------
# Session-scoped test data fixtures — Organizations group2
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def org_group2_file1() -> str:
    return load_text_file("organizations/group2/661197-2023.ttl")


@pytest.fixture(scope="session")
def org_group2_file2() -> str:
    return load_text_file("organizations/group2/663952-2023.ttl")


@pytest.fixture(scope="session")
def org_group2_file3() -> str:
    return load_text_file("organizations/group2/663952_-2023.ttl")


# ---------------------------------------------------------------------------
# Session-scoped test data fixtures — Procedures group1
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def proc_group1_file1() -> str:
    return load_text_file("procedures/group1/662861-2023.ttl")


@pytest.fixture(scope="session")
def proc_group1_file2() -> str:
    return load_text_file("procedures/group1/663131-2023.ttl")


@pytest.fixture(scope="session")
def proc_group1_file3() -> str:
    return load_text_file("procedures/group1/664733-2023.ttl")


# ---------------------------------------------------------------------------
# Session-scoped test data fixtures — Procedures group2
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def proc_group2_file1() -> str:
    return load_text_file("procedures/group2/661196-2023.ttl")


@pytest.fixture(scope="session")
def proc_group2_file2() -> str:
    return load_text_file("procedures/group2/663262-2023.ttl")


# ---------------------------------------------------------------------------
# RDF mapping
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def sample_rdf_mapping() -> str:
    return load_text_file("sample_rdf_mapping.yaml")
