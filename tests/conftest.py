import pytest
from erspec.models.core import ClusterReference, Decision

from tests.unit.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
)


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
