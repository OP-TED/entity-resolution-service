from pathlib import Path

import pytest
import redis.asyncio as aioredis
from erspec.models.core import ClusterReference, Decision
from testcontainers.redis import RedisContainer

TESTS_ROOT_DIR = Path(__file__).parent

from tests.unit.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
)


@pytest.fixture(scope="module")
def redis_container():
    """Start a Redis container once per test module. Skips if Docker is unavailable."""
    try:
        with RedisContainer() as container:
            yield container
    except Exception:
        pytest.skip("Docker not available")


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
