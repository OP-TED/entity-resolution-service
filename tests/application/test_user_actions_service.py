import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, create_autospec

import pytest

from ers.application.dtos import PaginatedResult, PaginationParams
from ers.application.ports.entity_mention_repository import EntityMentionRepository
from ers.application.ports.user_action_repository import UserActionRepository
from ers.application.services.user_action_service import UserActionService
from ers.domain.exceptions import AlreadyCuratedError
from tests.factories import DecisionFactory, EntityMentionFactory, UserActionFactory


@pytest.fixture
def user_action_repository() -> MagicMock:
    return create_autospec(UserActionRepository, instance=True)


@pytest.fixture
def entity_mention_repository() -> MagicMock:
    return create_autospec(EntityMentionRepository, instance=True)


@pytest.fixture
def user_action_service(
    user_action_repository: MagicMock,
    entity_mention_repository: MagicMock,
) -> UserActionService:
    return UserActionService(
        user_action_repository=user_action_repository,
        entity_mention_repository=entity_mention_repository,
    )


class TestRecordAccept:
    async def test_record_accept_saves_user_action(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        user_action_repository.has_current_action.return_value = False

        await user_action_service.record_accept(actor="curator-1", decision=decision)

        user_action_repository.save.assert_called_once()

    async def test_record_accept_already_curated_raises_error(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build(
            updated_at=datetime.now(timezone.utc),
        )
        user_action_repository.has_current_action.return_value = True

        with pytest.raises(AlreadyCuratedError) as exc_info:
            await user_action_service.record_accept(
                actor="curator-1", decision=decision
            )

        assert exc_info.value.decision_id == decision.id


class TestListUserActions:
    async def test_list_user_actions_returns_paginated_results(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        action = UserActionFactory.build()
        entity_mention = EntityMentionFactory.build(
            identifiedBy=action.about_entity_mention,
        )
        expected = PaginatedResult(count=1, previous=None, next=None, results=[action])
        pagination = PaginationParams(page=2, per_page=5)
        user_action_repository.find_paginated.return_value = expected
        entity_mention_repository.find_by_identifiers.return_value = [entity_mention]

        result = await user_action_service.list_user_actions(pagination)

        assert result.count == 1
        assert result.results[0].id == action.id
        assert (
            result.results[0].about_entity_mention.identified_by
            == action.about_entity_mention
        )
        assert result.results[
            0
        ].about_entity_mention.parsed_representation == json.loads(
            entity_mention.parsed_representation
        )
        user_action_repository.find_paginated.assert_called_once_with(pagination)
        entity_mention_repository.find_by_identifiers.assert_called_once_with(
            [action.about_entity_mention],
        )


class TestRecordReject:
    async def test_record_reject_saves_user_action(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        user_action_repository.has_current_action.return_value = False

        await user_action_service.record_reject(actor="curator-1", decision=decision)

        user_action_repository.save.assert_called_once()


class TestRecordAssign:
    async def test_record_assign_saves_user_action(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        target_id = decision.candidates[0].cluster_id
        user_action_repository.has_current_action.return_value = False

        await user_action_service.record_assign(
            actor="curator-1", decision=decision, cluster_id=target_id
        )

        user_action_repository.save.assert_called_once()

    async def test_record_assign_already_curated_raises_error(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build(
            updated_at=datetime.now(timezone.utc),
        )
        user_action_repository.has_current_action.return_value = True

        with pytest.raises(AlreadyCuratedError):
            await user_action_service.record_assign(
                actor="curator-1",
                decision=decision,
                cluster_id=decision.candidates[0].cluster_id,
            )
