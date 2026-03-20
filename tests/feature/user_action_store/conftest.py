"""Shared fixtures for user_action_store BDD step definitions.

Tests at the service layer with mocked repositories.
"""

from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from ers.curation.adapters import (
    EntityMentionCurationRepository,
    UserActionCurationRepository,
)
from ers.curation.services import UserActionService


@pytest.fixture
def ctx() -> dict[str, Any]:
    """Shared mutable context for passing state between step functions."""
    return {}


@pytest.fixture
def user_action_repository() -> MagicMock:
    return create_autospec(UserActionCurationRepository, instance=True)


@pytest.fixture
def entity_mention_repository() -> MagicMock:
    return create_autospec(EntityMentionCurationRepository, instance=True)


@pytest.fixture
def user_action_service(
    user_action_repository: MagicMock,
    entity_mention_repository: MagicMock,
) -> UserActionService:
    return UserActionService(
        user_action_repository=user_action_repository,
        entity_mention_repository=entity_mention_repository,
    )
