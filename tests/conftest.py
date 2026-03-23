from pathlib import Path

import pytest
import redis.asyncio as aioredis
from erspec.models.core import ClusterReference, Decision
from testcontainers.redis import RedisContainer

# Path constants — single source of truth for test directory structure
TESTS_ROOT_DIR = Path(__file__).parent
TEST_DATA_DIR = TESTS_ROOT_DIR / "test_data"


@pytest.fixture(scope="module")
def redis_container():
    """Start a Redis container once per test module. Fails if Docker is unavailable."""
    try:
        with RedisContainer() as container:
            yield container
    except Exception as exc:
        pytest.fail(f"Redis container could not be started (is Docker running?): {exc}")


@pytest.fixture
async def redis_client(redis_container) -> aioredis.Redis:
    """Provide a live aioredis.Redis client connected to the test container.

    Flushes the database and closes the client after each test.
    """
    client = aioredis.Redis(
        host=redis_container.get_container_host_ip(),
        port=int(redis_container.get_exposed_port(6379)),
    )
    yield client
    await client.flushdb()
    await client.aclose()


def pytest_collection_modifyitems(items: list) -> None:
    """Automatically apply test-type markers based on directory location.

    pytest does not honour ``pytestmark`` defined in ``conftest.py`` files
    (conftest is loaded as a plugin, not a test module).  This hook is the
    correct place to stamp every collected item with its test-type marker so
    that ``-m unit``, ``-m feature``, ``-m integration``, and ``-m e2e``
    filter correctly without any per-file decoration.

    Marker-to-directory mapping:

    * ``unit``        — ``tests/unit/``
    * ``feature``     — ``tests/feature/``
    * ``integration`` — ``tests/integration/``
    * ``e2e``         — ``tests/e2e/``
    """
    for item in items:
        path = str(item.fspath)
        if "/tests/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/tests/feature/" in path:
            item.add_marker(pytest.mark.feature)
        elif "/tests/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "/tests/e2e/" in path:
            item.add_marker(pytest.mark.e2e)


# ============================================================================
# Helper: Load RDF content by relative path
# ============================================================================


def load_text_file(relative_path: str) -> str:
    """
    Load RDF content from test_data directory.

    Args:
        relative_path: Path relative to test_data/, e.g., "organizations/group1/661238-2023.ttl"

    Returns:
        str: Full RDF/Turtle content

    Raises:
        FileNotFoundError: If file does not exist
    """
    file_path = TEST_DATA_DIR / relative_path
    if not file_path.exists():
        raise FileNotFoundError(f"Test data file not found: {file_path}")
    return file_path.read_text(encoding="utf-8")


# ============================================================================
# Organizations Test Data Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def org_group1_file1() -> str:
    """Organizations group1, file 1."""
    return load_text_file("organizations/group1/661238-2023.ttl")


@pytest.fixture(scope="session")
def org_group1_file2() -> str:
    """Organizations group1, file 2."""
    return load_text_file("organizations/group1/662860-2023.ttl")


@pytest.fixture(scope="session")
def org_group1_file3() -> str:
    """Organizations group1, file 3."""
    return load_text_file("organizations/group1/663653-2023.ttl")


@pytest.fixture(scope="session")
def org_group2_file1() -> str:
    """Organizations group2, file 1."""
    return load_text_file("organizations/group2/661197-2023.ttl")


@pytest.fixture(scope="session")
def org_group2_file2() -> str:
    """Organizations group2, file 2."""
    return load_text_file("organizations/group2/663952-2023.ttl")


# ============================================================================
# Procedures Test Data Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def proc_group1_file1() -> str:
    """Procedures group1, file 1."""
    return load_text_file("procedures/group1/662861-2023.ttl")


@pytest.fixture(scope="session")
def proc_group1_file2() -> str:
    """Procedures group1, file 2."""
    return load_text_file("procedures/group1/663131-2023.ttl")


@pytest.fixture(scope="session")
def proc_group1_file3() -> str:
    """Procedures group1, file 3."""
    return load_text_file("procedures/group1/664733-2023.ttl")


@pytest.fixture(scope="session")
def proc_group2_file1() -> str:
    """Procedures group2, file 1."""
    return load_text_file("procedures/group2/661196-2023.ttl")


@pytest.fixture(scope="session")
def proc_group2_file2() -> str:
    """Procedures group2, file 2."""
    return load_text_file("procedures/group2/663262-2023.ttl")


# ============================================================================
# rdf_mapping YAML file
# ============================================================================


@pytest.fixture(scope="session")
def sample_rdf_mapping() -> str:
    """path to sample_rdf_mapping"""
    return load_text_file("sample_rdf_mapping.yaml")
