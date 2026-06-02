"""C4 wider sweep: every public read on a curation service must translate
PyMongo ``ConnectionFailure`` to ``ServiceUnavailableError`` so the curation
API exception handler maps Mongo outages to HTTP 503 instead of 500.

Each test injects a repository mock that raises ``ConnectionFailure`` on the
first inbound call and asserts the wrapping service surfaces a
``ServiceUnavailableError`` with ``service_name == "mongodb"``.
"""

from unittest.mock import create_autospec

import pytest
from pymongo.errors import ConnectionFailure

from ers.commons.domain.data_transfer_objects import CursorParams
from ers.commons.services.exceptions import ServiceUnavailableError
from ers.curation.adapters import (
    EntityMentionCurationRepository,
    ReviewStateReader,
    StatisticsRepository,
    UserActionCurationRepository,
)
from ers.curation.domain.data_transfer_objects import StatisticsFilters
from ers.curation.services import (
    CanonicalEntityService,
    DecisionCurationService,
    EntityService,
    StatisticsService,
    UserActionService,
)
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from ers.resolution_decision_store.adapters.decision_repository import DecisionRepository
from ers.users.adapters.user_repository import UserRepository
from test.unit.factories import EntityMentionIdentifierFactory


class TestStatisticsServiceTranslation:
    async def test_get_statistics_translates_connection_failure(self) -> None:
        repo = create_autospec(StatisticsRepository, instance=True)
        repo.get_curation_statistics.side_effect = ConnectionFailure("Mongo down")
        repo.get_registry_statistics.side_effect = ConnectionFailure("Mongo down")
        service = StatisticsService(statistics_repository=repo)

        with pytest.raises(ServiceUnavailableError) as exc_info:
            await service.get_statistics(StatisticsFilters())
        assert exc_info.value.service_name == "mongodb"


class TestEntityServiceTranslation:
    async def test_get_entity_mention_translates_connection_failure(self) -> None:
        repo = create_autospec(EntityMentionCurationRepository, instance=True)
        repo.find_by_triad.side_effect = ConnectionFailure("Mongo down")
        service = EntityService(entity_mention_repository=repo)

        ident = EntityMentionIdentifierFactory.build()
        with pytest.raises(ServiceUnavailableError) as exc_info:
            await service.get_entity_mention(ident)
        assert exc_info.value.service_name == "mongodb"


class TestUserActionServiceTranslation:
    async def test_list_user_actions_translates_connection_failure(self) -> None:
        user_action_repo = create_autospec(
            UserActionCurationRepository, instance=True
        )
        user_action_repo.find_with_cursor.side_effect = ConnectionFailure(
            "Mongo down"
        )
        entity_repo = create_autospec(EntityMentionCurationRepository, instance=True)
        user_repo = create_autospec(UserRepository, instance=True)
        decision_repo = create_autospec(DecisionRepository, instance=True)
        service = UserActionService(
            user_action_repository=user_action_repo,
            entity_mention_repository=entity_repo,
            user_repository=user_repo,
            decision_repository=decision_repo,
        )

        with pytest.raises(ServiceUnavailableError) as exc_info:
            await service.list_user_actions(cursor_params=CursorParams())
        assert exc_info.value.service_name == "mongodb"


class TestCanonicalEntityServiceTranslation:
    async def test_get_proposed_canonical_entity_translates_connection_failure(self) -> None:
        decision_repo = create_autospec(DecisionRepository, instance=True)
        decision_repo.find_by_id.side_effect = ConnectionFailure("Mongo down")
        entity_repo = create_autospec(EntityMentionCurationRepository, instance=True)
        service = CanonicalEntityService(
            decision_repository=decision_repo,
            entity_mention_repository=entity_repo,
        )

        with pytest.raises(ServiceUnavailableError) as exc_info:
            await service.get_proposed_canonical_entity("decision-id")
        assert exc_info.value.service_name == "mongodb"


class TestDecisionCurationServiceTranslation:
    async def test_get_decision_translates_connection_failure(self) -> None:
        decision_repo = create_autospec(DecisionRepository, instance=True)
        decision_repo.find_by_id.side_effect = ConnectionFailure("Mongo down")
        entity_repo = create_autospec(EntityMentionCurationRepository, instance=True)
        user_action_service = create_autospec(UserActionService, instance=True)
        ere_publish_service = create_autospec(EREPublishService, instance=True)
        review_state_reader = create_autospec(ReviewStateReader, instance=True)
        service = DecisionCurationService(
            decision_repository=decision_repo,
            entity_mention_repository=entity_repo,
            user_action_service=user_action_service,
            ere_publish_service=ere_publish_service,
            review_state_reader=review_state_reader,
        )

        with pytest.raises(ServiceUnavailableError) as exc_info:
            await service.get_decision("decision-id")
        assert exc_info.value.service_name == "mongodb"
