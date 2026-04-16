"""Shared fixtures for Resolution Decision Store BDD tests."""
from unittest.mock import create_autospec

import pytest

from ers.resolution_decision_store.adapters.decision_repository import (
    MongoDecisionRepository,
)
from ers.resolution_decision_store.services.decision_store_service import (
    DecisionStoreService,
)


@pytest.fixture()
def ctx():
    """Mutable context for passing state between step functions."""
    return {}


@pytest.fixture()
def mock_repo():
    """Auto-mocked MongoDecisionRepository for BDD scenarios."""
    return create_autospec(MongoDecisionRepository, instance=True)


@pytest.fixture()
def service(mock_repo):
    """DecisionStoreService with mocked repository."""
    return DecisionStoreService(repository=mock_repo)
