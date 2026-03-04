import json
from unittest.mock import MagicMock, create_autospec

import pytest

from ers.application.dtos import (
    DecisionFilters,
    DecisionSummary,
    PaginatedResult,
    PaginationParams,
)
from ers.application.exceptions import NotFoundError
from ers.application.ports.decision_repository import DecisionRepository
from ers.application.ports.entity_mention_repository import EntityMentionRepository
from ers.application.services.decision_curation_service import (
    DecisionCurationService,
)
from ers.application.services.user_action_service import UserActionService
from tests.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
    EntityMentionFactory,
    EntityMentionIdentifierFactory,
)


@pytest.fixture
def decision_repository() -> MagicMock:
    return create_autospec(DecisionRepository, instance=True)


@pytest.fixture
def entity_mention_repository() -> MagicMock:
    return create_autospec(EntityMentionRepository, instance=True)


@pytest.fixture
def user_action_service() -> MagicMock:
    return create_autospec(UserActionService, instance=True)


@pytest.fixture
def service(
    decision_repository: MagicMock,
    entity_mention_repository: MagicMock,
    user_action_service: MagicMock,
) -> DecisionCurationService:
    return DecisionCurationService(
        decision_repository=decision_repository,
        entity_mention_repository=entity_mention_repository,
        user_action_service=user_action_service,
    )


class TestListDecisions:
    async def test_list_decisions_returns_decision_summaries(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        entity_mention = EntityMentionFactory.build(
            identifiedBy=decision.about_entity_mention,
        )
        decision_repository.find_with_filters.return_value = PaginatedResult(
            count=1,
            previous=None,
            next=None,
            results=[decision],
        )
        entity_mention_repository.find_by_identifiers.return_value = [entity_mention]

        result = await service.list_decisions(
            filters=DecisionFilters(),
            pagination=PaginationParams(),
        )

        assert result.count == 1
        summary = result.results[0]
        assert isinstance(summary, DecisionSummary)
        assert summary.id == decision.id
        assert (
            summary.about_entity_mention.identified_by == decision.about_entity_mention
        )
        assert summary.about_entity_mention.parsed_representation == json.loads(
            entity_mention.parsed_representation
        )

    async def test_list_decisions_empty_results(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        decision_repository.find_with_filters.return_value = PaginatedResult(
            count=0,
            previous=None,
            next=None,
            results=[],
        )
        entity_mention_repository.find_by_identifiers.return_value = []

        result = await service.list_decisions(
            filters=DecisionFilters(),
            pagination=PaginationParams(),
        )

        assert result.count == 0
        assert result.results == []

    async def test_list_decisions_with_search_delegates_to_entity_search(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        identifiers = EntityMentionIdentifierFactory.batch(2)
        decision = DecisionFactory.build(about_entity_mention=identifiers[0])
        mention = EntityMentionFactory.build(identifiedBy=identifiers[0])

        entity_mention_repository.search_identifiers.return_value = identifiers
        decision_repository.find_with_filters.return_value = PaginatedResult(
            count=1,
            results=[decision],
        )
        entity_mention_repository.find_by_identifiers.return_value = [mention]

        result = await service.list_decisions(
            filters=DecisionFilters(search="example"),
            pagination=PaginationParams(),
        )

        entity_mention_repository.search_identifiers.assert_called_once_with("example")
        decision_repository.find_with_filters.assert_called_once_with(
            filters=DecisionFilters(search="example"),
            pagination=PaginationParams(),
            mention_identifiers=identifiers,
        )
        assert result.count == 1

    async def test_list_decisions_with_search_no_matches_returns_empty(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        entity_mention_repository.search_identifiers.return_value = []

        result = await service.list_decisions(
            filters=DecisionFilters(search="nonexistent"),
            pagination=PaginationParams(),
        )

        assert result.count == 0
        assert result.results == []
        decision_repository.find_with_filters.assert_not_called()

    async def test_list_decisions_without_search_skips_entity_search(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        decision_repository.find_with_filters.return_value = PaginatedResult(
            count=0,
            results=[],
        )
        entity_mention_repository.find_by_identifiers.return_value = []

        await service.list_decisions(
            filters=DecisionFilters(),
            pagination=PaginationParams(),
        )

        entity_mention_repository.search_identifiers.assert_not_called()
        decision_repository.find_with_filters.assert_called_once_with(
            filters=DecisionFilters(),
            pagination=PaginationParams(),
            mention_identifiers=None,
        )


class TestGetDecision:
    async def test_get_decision_returns_decision(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        decision_repository.find_by_id.return_value = decision

        result = await service.get_decision(decision.id)

        assert result == decision

    async def test_get_decision_not_found_raises_error(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
    ) -> None:
        decision_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError) as exc_info:
            await service.get_decision("nonexistent-id")

        assert exc_info.value.entity_type == "Decision"
        assert exc_info.value.entity_id == "nonexistent-id"


class TestAcceptDecision:
    async def test_accept_decision_delegates_to_user_action_service(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        user_action_service: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        decision_repository.find_by_id.return_value = decision

        await service.accept_decision(decision.id, actor="curator-1")

        user_action_service.record_accept.assert_called_once_with(
            actor="curator-1", decision=decision
        )

    async def test_accept_decision_does_not_save_decision(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        user_action_service: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        decision_repository.find_by_id.return_value = decision

        await service.accept_decision(decision.id, actor="curator-1")

        decision_repository.save.assert_not_called()

    async def test_accept_decision_not_found_raises_error(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        user_action_service: MagicMock,
    ) -> None:
        decision_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.accept_decision("nonexistent-id", actor="curator-1")

        user_action_service.record_accept.assert_not_called()


class TestRejectDecision:
    async def test_reject_decision_delegates_to_user_action_service(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        user_action_service: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        decision_repository.find_by_id.return_value = decision

        await service.reject_decision(decision.id, actor="curator-1")

        user_action_service.record_reject.assert_called_once_with(
            actor="curator-1", decision=decision
        )

    async def test_reject_decision_not_found_raises_error(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
    ) -> None:
        decision_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.reject_decision("nonexistent-id", actor="curator-1")


class TestAssignDecision:
    async def test_assign_decision_delegates_to_user_action_service(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        user_action_service: MagicMock,
    ) -> None:
        target = ClusterReferenceFactory.build()
        decision = DecisionFactory.build(
            candidates=[ClusterReferenceFactory.build(), target],
        )
        decision_repository.find_by_id.return_value = decision

        await service.assign_decision(
            decision.id, cluster_id=target.cluster_id, actor="curator-1"
        )

        user_action_service.record_assign.assert_called_once_with(
            actor="curator-1",
            decision=decision,
            cluster_id=target.cluster_id,
        )

    async def test_assign_decision_does_not_save_decision(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        user_action_service: MagicMock,
    ) -> None:
        target = ClusterReferenceFactory.build()
        decision = DecisionFactory.build(
            candidates=[ClusterReferenceFactory.build(), target],
        )
        decision_repository.find_by_id.return_value = decision

        await service.assign_decision(
            decision.id, cluster_id=target.cluster_id, actor="curator-1"
        )

        decision_repository.save.assert_not_called()

    async def test_assign_decision_not_found_raises_error(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
    ) -> None:
        decision_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.assign_decision(
                "nonexistent-id", cluster_id="some-cluster", actor="curator-1"
            )
