import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, create_autospec

import pytest
from erspec.models.core import UserActionType

from ers.commons.domain.data_transfer_objects import (
    CursorPage,
    CursorParams,
    PaginatedResult,
    PaginationParams,
)
from ers.commons.services.exceptions import NotFoundError
from ers.curation.adapters import (
    DecisionCurationRepository,
    EntityMentionCurationRepository,
    UserActionCurationRepository,
)
from ers.curation.domain.data_transfer_objects import CanonicalEntityPreview, UserActionFilters
from ers.curation.domain.exceptions import AlreadyCuratedError
from ers.curation.services import CanonicalEntityService, UserActionService
from tests.unit.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
    EntityMentionFactory,
    EntityMentionIdentifierFactory,
    UserActionFactory,
)


@pytest.fixture
def user_action_repository() -> MagicMock:
    return create_autospec(UserActionCurationRepository, instance=True)


@pytest.fixture
def entity_mention_repository() -> MagicMock:
    return create_autospec(EntityMentionCurationRepository, instance=True)


@pytest.fixture
def decision_repository() -> MagicMock:
    return create_autospec(DecisionCurationRepository, instance=True)


@pytest.fixture
def canonical_entity_service(
    decision_repository: MagicMock,
    entity_mention_repository: MagicMock,
) -> CanonicalEntityService:
    return CanonicalEntityService(
        decision_repository=decision_repository,
        entity_mention_repository=entity_mention_repository,
    )


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
            updated_at=datetime.now(UTC),
        )
        user_action_repository.has_current_action.return_value = True

        with pytest.raises(AlreadyCuratedError) as exc_info:
            await user_action_service.record_accept(actor="curator-1", decision=decision)

        assert exc_info.value.decision_id == decision.id


class TestListUserActions:
    async def test_list_user_actions_returns_cursor_paginated_results(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        action = UserActionFactory.build()
        entity_mention = EntityMentionFactory.build(
            identifiedBy=action.about_entity_mention,
        )
        expected = CursorPage(results=[action], next_cursor=None)
        cursor_params = CursorParams(cursor=None, limit=5)
        user_action_repository.find_with_cursor.return_value = expected
        entity_mention_repository.find_by_identifiers.return_value = [entity_mention]

        result = await user_action_service.list_user_actions(cursor_params)

        assert len(result.results) == 1
        assert result.results[0].id == action.id
        assert result.results[0].about_entity_mention.identified_by == action.about_entity_mention
        assert result.results[0].about_entity_mention.parsed_representation == json.loads(
            entity_mention.parsed_representation
        )
        assert result.next_cursor is None
        user_action_repository.find_with_cursor.assert_called_once_with(cursor_params, None)
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
            updated_at=datetime.now(UTC),
        )
        user_action_repository.has_current_action.return_value = True

        with pytest.raises(AlreadyCuratedError):
            await user_action_service.record_assign(
                actor="curator-1",
                decision=decision,
                cluster_id=decision.candidates[0].cluster_id,
            )


class TestListUserActionsFiltered:
    async def test_passes_filters_to_repository(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        user_action_repository.find_with_cursor.return_value = CursorPage(
            results=[],
        )
        entity_mention_repository.find_by_identifiers.return_value = []
        filters = UserActionFilters(action_type=UserActionType.ACCEPT_TOP)
        cursor_params = CursorParams(limit=10)

        await user_action_service.list_user_actions(cursor_params, filters)

        user_action_repository.find_with_cursor.assert_called_once_with(cursor_params, filters)

    async def test_filter_by_actor(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        action = UserActionFactory.build(actor="curator@example.com")
        user_action_repository.find_with_cursor.return_value = CursorPage(
            results=[action],
        )
        entity_mention_repository.find_by_identifiers.return_value = []
        filters = UserActionFilters(actor="curator@example.com")

        result = await user_action_service.list_user_actions(CursorParams(), filters)

        assert len(result.results) == 1
        assert result.results[0].actor == "curator@example.com"

    async def test_filter_by_time_range(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        start = datetime(2026, 3, 13, tzinfo=UTC)
        end = datetime(2026, 3, 20, tzinfo=UTC)
        action = UserActionFactory.build()
        user_action_repository.find_with_cursor.return_value = CursorPage(
            results=[action],
        )
        entity_mention_repository.find_by_identifiers.return_value = []
        filters = UserActionFilters(time_range_start=start, time_range_end=end)

        result = await user_action_service.list_user_actions(CursorParams(), filters)

        assert len(result.results) == 1
        user_action_repository.find_with_cursor.assert_called_once_with(
            CursorParams(),
            filters,
        )

    async def test_no_filters_passes_none(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        entity_mention_repository: MagicMock,
    ) -> None:
        user_action_repository.find_with_cursor.return_value = CursorPage(
            results=[],
        )
        entity_mention_repository.find_by_identifiers.return_value = []

        await user_action_service.list_user_actions(CursorParams())

        user_action_repository.find_with_cursor.assert_called_once_with(
            CursorParams(),
            None,
        )


class TestGetSelectedClusterPreview:
    async def test_returns_preview_with_embedded_entities(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        canonical_entity_service: CanonicalEntityService,
    ) -> None:
        selected = ClusterReferenceFactory.build()
        action = UserActionFactory.build(selected_cluster=selected)
        member_ids = EntityMentionIdentifierFactory.batch(3)
        mentions = [EntityMentionFactory.build(identifiedBy=mid) for mid in member_ids]

        user_action_repository.find_by_id.return_value = action
        decision_repository.find_mention_ids_by_cluster.return_value = member_ids
        entity_mention_repository.find_by_identifiers.return_value = mentions

        result = await user_action_service.get_selected_cluster_preview(
            action.id, canonical_entity_service
        )

        assert isinstance(result, CanonicalEntityPreview)
        assert result.cluster_id == selected.cluster_id
        assert result.confidence_score == selected.confidence_score
        assert len(result.top_entities) == 3

    async def test_not_found_raises_error(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        canonical_entity_service: CanonicalEntityService,
    ) -> None:
        user_action_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError) as exc_info:
            await user_action_service.get_selected_cluster_preview(
                "nonexistent", canonical_entity_service
            )
        assert exc_info.value.entity_type == "UserAction"

    async def test_no_selected_cluster_returns_none(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        canonical_entity_service: CanonicalEntityService,
    ) -> None:
        action = UserActionFactory.build(selected_cluster=None)
        user_action_repository.find_by_id.return_value = action

        result = await user_action_service.get_selected_cluster_preview(
            action.id, canonical_entity_service
        )
        assert result is None


class TestGetCandidatePreviews:
    async def test_returns_paginated_candidates(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        canonical_entity_service: CanonicalEntityService,
    ) -> None:
        candidates = ClusterReferenceFactory.batch(3)
        action = UserActionFactory.build(candidates=candidates, selected_cluster=None)

        user_action_repository.find_by_id.return_value = action
        decision_repository.find_mention_ids_by_cluster.return_value = (
            EntityMentionIdentifierFactory.batch(2)
        )
        entity_mention_repository.find_by_identifiers.return_value = EntityMentionFactory.batch(2)

        result = await user_action_service.get_candidate_previews(
            action.id, PaginationParams(page=1, per_page=10), canonical_entity_service
        )

        assert isinstance(result, PaginatedResult)
        assert result.count == 3
        assert len(result.results) == 3
        assert result.next is None
        assert result.previous is None

    async def test_pagination_returns_correct_page(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        canonical_entity_service: CanonicalEntityService,
    ) -> None:
        candidates = ClusterReferenceFactory.batch(5)
        action = UserActionFactory.build(candidates=candidates, selected_cluster=None)

        user_action_repository.find_by_id.return_value = action
        decision_repository.find_mention_ids_by_cluster.return_value = (
            EntityMentionIdentifierFactory.batch(2)
        )
        entity_mention_repository.find_by_identifiers.return_value = EntityMentionFactory.batch(2)

        result = await user_action_service.get_candidate_previews(
            action.id, PaginationParams(page=1, per_page=2), canonical_entity_service
        )

        assert result.count == 5
        assert len(result.results) == 2
        assert result.next == 2
        assert result.previous is None

    async def test_second_page(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        canonical_entity_service: CanonicalEntityService,
    ) -> None:
        candidates = ClusterReferenceFactory.batch(3)
        action = UserActionFactory.build(candidates=candidates, selected_cluster=None)

        user_action_repository.find_by_id.return_value = action
        decision_repository.find_mention_ids_by_cluster.return_value = (
            EntityMentionIdentifierFactory.batch(1)
        )
        entity_mention_repository.find_by_identifiers.return_value = EntityMentionFactory.batch(1)

        result = await user_action_service.get_candidate_previews(
            action.id, PaginationParams(page=2, per_page=2), canonical_entity_service
        )

        assert result.count == 3
        assert len(result.results) == 1
        assert result.previous == 1
        assert result.next is None

    async def test_not_found_raises_error(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        canonical_entity_service: CanonicalEntityService,
    ) -> None:
        user_action_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await user_action_service.get_candidate_previews(
                "nonexistent", PaginationParams(), canonical_entity_service
            )

    async def test_candidates_sorted_by_confidence_desc(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        canonical_entity_service: CanonicalEntityService,
    ) -> None:
        low = ClusterReferenceFactory.build(confidence_score=0.3)
        high = ClusterReferenceFactory.build(confidence_score=0.9)
        mid = ClusterReferenceFactory.build(confidence_score=0.6)
        action = UserActionFactory.build(candidates=[low, high, mid], selected_cluster=None)

        user_action_repository.find_by_id.return_value = action
        decision_repository.find_mention_ids_by_cluster.return_value = []
        entity_mention_repository.find_by_identifiers.return_value = []

        result = await user_action_service.get_candidate_previews(
            action.id, PaginationParams(page=1, per_page=10), canonical_entity_service
        )

        scores = [r.confidence_score for r in result.results]
        assert scores == sorted(scores, reverse=True)

    async def test_excludes_selected_cluster_from_candidates(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        canonical_entity_service: CanonicalEntityService,
    ) -> None:
        selected = ClusterReferenceFactory.build(confidence_score=0.95)
        other = ClusterReferenceFactory.build(confidence_score=0.7)
        action = UserActionFactory.build(
            candidates=[selected, other],
            selected_cluster=selected,
        )

        user_action_repository.find_by_id.return_value = action
        decision_repository.find_mention_ids_by_cluster.return_value = []
        entity_mention_repository.find_by_identifiers.return_value = []

        result = await user_action_service.get_candidate_previews(
            action.id, PaginationParams(page=1, per_page=10), canonical_entity_service
        )

        assert result.count == 1
        assert result.results[0].cluster_id == other.cluster_id
