import json
from unittest.mock import MagicMock, create_autospec

import pytest

from ers.commons.domain.data_transfer_objects import CursorPage, CursorParams
from ers.commons.services.exceptions import NotFoundError
from ers.curation.adapters import (
    DecisionCurationRepository,
    EntityMentionCurationRepository,
)
from ers.curation.domain.data_transfer_objects import (
    BulkActionResponse,
    BulkItemStatus,
    DecisionFilters,
    DecisionSummary,
)
from ers.curation.domain.exceptions import AlreadyCuratedError
from ers.curation.services import DecisionCurationService, UserActionService
from tests.unit.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
    EntityMentionFactory,
    EntityMentionIdentifierFactory,
)


@pytest.fixture
def decision_repository() -> MagicMock:
    return create_autospec(DecisionCurationRepository, instance=True)


@pytest.fixture
def entity_mention_repository() -> MagicMock:
    return create_autospec(EntityMentionCurationRepository, instance=True)


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
        decision_repository.find_with_filters.return_value = CursorPage(
            results=[decision],
            next_cursor=None,
        )
        entity_mention_repository.find_by_identifiers.return_value = [entity_mention]

        result = await service.list_decisions(
            filters=DecisionFilters(),
            cursor_params=CursorParams(),
        )

        assert len(result.results) == 1
        summary = result.results[0]
        assert isinstance(summary, DecisionSummary)
        assert summary.id == decision.id
        assert summary.about_entity_mention.identified_by == decision.about_entity_mention
        assert summary.about_entity_mention.parsed_representation == json.loads(
            entity_mention.parsed_representation
        )

    async def test_list_decisions_empty_results(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        decision_repository.find_with_filters.return_value = CursorPage(
            results=[],
            next_cursor=None,
        )
        entity_mention_repository.find_by_identifiers.return_value = []

        result = await service.list_decisions(
            filters=DecisionFilters(),
            cursor_params=CursorParams(),
        )

        assert result.results == []
        assert result.next_cursor is None

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
        decision_repository.find_with_filters.return_value = CursorPage(
            results=[decision],
            next_cursor=None,
        )
        entity_mention_repository.find_by_identifiers.return_value = [mention]

        result = await service.list_decisions(
            filters=DecisionFilters(search="example"),
            cursor_params=CursorParams(),
        )

        entity_mention_repository.search_identifiers.assert_called_once_with("example")
        decision_repository.find_with_filters.assert_called_once_with(
            filters=DecisionFilters(search="example"),
            cursor_params=CursorParams(),
            mention_identifiers=identifiers,
        )
        assert len(result.results) == 1

    async def test_list_decisions_with_search_no_matches_returns_empty(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        entity_mention_repository.search_identifiers.return_value = []

        result = await service.list_decisions(
            filters=DecisionFilters(search="nonexistent"),
            cursor_params=CursorParams(),
        )

        assert result.results == []
        assert result.next_cursor is None
        decision_repository.find_with_filters.assert_not_called()

    async def test_list_decisions_without_search_skips_entity_search(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        decision_repository.find_with_filters.return_value = CursorPage(
            results=[],
            next_cursor=None,
        )
        entity_mention_repository.find_by_identifiers.return_value = []

        await service.list_decisions(
            filters=DecisionFilters(),
            cursor_params=CursorParams(),
        )

        entity_mention_repository.search_identifiers.assert_not_called()
        decision_repository.find_with_filters.assert_called_once_with(
            filters=DecisionFilters(),
            cursor_params=CursorParams(),
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

        await service.assign_decision(decision.id, cluster_id=target.cluster_id, actor="curator-1")

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

        await service.assign_decision(decision.id, cluster_id=target.cluster_id, actor="curator-1")

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


class TestBulkAcceptDecisions:
    async def test_all_successful(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        user_action_service: MagicMock,
    ) -> None:
        decisions = DecisionFactory.batch(3)
        decision_repository.find_by_id.side_effect = decisions

        result = await service.bulk_accept_decisions([d.id for d in decisions], actor="curator-1")

        assert isinstance(result, BulkActionResponse)
        assert len(result.results) == 3
        assert all(r.status == BulkItemStatus.SUCCESS for r in result.results)
        assert [r.decision_id for r in result.results] == [d.id for d in decisions]

    async def test_preserves_order_and_reports_per_item_status(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        user_action_service: MagicMock,
    ) -> None:
        existing = DecisionFactory.build()
        decision_repository.find_by_id.side_effect = [
            existing,
            None,
            existing,
        ]
        user_action_service.record_accept.side_effect = [
            None,
            AlreadyCuratedError(existing.id),
        ]

        result = await service.bulk_accept_decisions(
            [existing.id, "missing-id", existing.id], actor="curator-1"
        )

        assert result.results[0].status == BulkItemStatus.SUCCESS
        assert result.results[1].status == BulkItemStatus.NOT_FOUND
        assert result.results[2].status == BulkItemStatus.ALREADY_CURATED

    async def test_already_curated_does_not_fail_request(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        user_action_service: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        decision_repository.find_by_id.return_value = decision
        user_action_service.record_accept.side_effect = AlreadyCuratedError(decision.id)

        result = await service.bulk_accept_decisions([decision.id], actor="curator-1")

        assert result.results[0].status == BulkItemStatus.ALREADY_CURATED
        assert result.results[0].detail is None


class TestBulkRejectDecisions:
    async def test_all_successful(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        user_action_service: MagicMock,
    ) -> None:
        decisions = DecisionFactory.batch(3)
        decision_repository.find_by_id.side_effect = decisions

        result = await service.bulk_reject_decisions([d.id for d in decisions], actor="curator-1")

        assert len(result.results) == 3
        assert all(r.status == BulkItemStatus.SUCCESS for r in result.results)

    async def test_mixed_results(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        user_action_service: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        decision_repository.find_by_id.side_effect = [decision, None]
        user_action_service.record_reject.return_value = None

        result = await service.bulk_reject_decisions([decision.id, "missing-id"], actor="curator-1")

        assert result.results[0].status == BulkItemStatus.SUCCESS
        assert result.results[1].status == BulkItemStatus.NOT_FOUND

    async def test_unexpected_error_captured_with_detail(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        user_action_service: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        decision_repository.find_by_id.return_value = decision
        user_action_service.record_reject.side_effect = RuntimeError("db timeout")

        result = await service.bulk_reject_decisions([decision.id], actor="curator-1")

        assert result.results[0].status == BulkItemStatus.ERROR
        assert result.results[0].detail == "db timeout"
