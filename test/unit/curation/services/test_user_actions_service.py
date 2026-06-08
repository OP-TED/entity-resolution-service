import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, create_autospec

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
    DecisionRepository,
    EntityMentionCurationRepository,
    UserActionCurationRepository,
)
from ers.curation.domain.data_transfer_objects import (
    CanonicalEntityPreview,
    UserActionFilters,
)
from ers.curation.domain.exceptions import AlreadyCuratedError
from ers.curation.services import CanonicalEntityService, UserActionService
from ers.users.adapters.user_repository import UserRepository
from test.unit.factories import (
    ClusterReferenceFactory,
    DecisionFactory,
    EntityMentionFactory,
    EntityMentionIdentifierFactory,
    UserActionFactory,
    UserFactory,
)


@pytest.fixture
def user_action_repository() -> MagicMock:
    return create_autospec(UserActionCurationRepository, instance=True)


@pytest.fixture
def entity_mention_repository() -> MagicMock:
    return create_autospec(EntityMentionCurationRepository, instance=True)


@pytest.fixture
def user_repository() -> MagicMock:
    return create_autospec(UserRepository, instance=True)


@pytest.fixture
def decision_repository() -> MagicMock:
    mock = create_autospec(DecisionRepository, instance=True)
    mock.record_review = AsyncMock()
    mock.find_review_metadata.return_value = {}
    return mock


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
    user_repository: MagicMock,
    decision_repository: MagicMock,
) -> UserActionService:
    return UserActionService(
        user_action_repository=user_action_repository,
        entity_mention_repository=entity_mention_repository,
        user_repository=user_repository,
        decision_repository=decision_repository,
    )


class TestRaceSafeRecord:
    """Unit tests for the atomic claim-based idempotency.

    ``record_review`` returns ``bool`` — True iff the conditional update on
    the decision row matched. The service treats False as "lost the race",
    deletes the just-saved user_action (compensation), and raises
    ``AlreadyCuratedError``. This closes the TOCTOU race the previous
    read-then-write guard left open.
    """

    async def test_record_accept_claim_succeeds_no_compensation(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
    ) -> None:
        """When record_review returns True, the audit row stays and no delete fires."""
        decision = DecisionFactory.build()
        user_action_repository.save = AsyncMock()
        user_action_repository.delete_by_id = AsyncMock()
        decision_repository.record_review = AsyncMock(return_value=True)

        await user_action_service.record_accept(actor="curator-1", decision=decision)

        user_action_repository.save.assert_awaited_once()
        decision_repository.record_review.assert_awaited_once()
        user_action_repository.delete_by_id.assert_not_called()

    async def test_record_accept_claim_lost_compensates_and_raises(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
    ) -> None:
        """When record_review returns False, the just-saved audit row is deleted
        and AlreadyCuratedError is raised."""
        decision = DecisionFactory.build()
        user_action_repository.save = AsyncMock()
        user_action_repository.delete_by_id = AsyncMock()
        decision_repository.record_review = AsyncMock(return_value=False)

        with pytest.raises(AlreadyCuratedError) as exc_info:
            await user_action_service.record_accept(
                actor="curator-1", decision=decision
            )

        assert exc_info.value.decision_id == decision.id
        # Compensation: the action passed to save must be the one passed to delete_by_id.
        saved_action = user_action_repository.save.await_args.args[0]
        user_action_repository.delete_by_id.assert_awaited_once_with(saved_action.id)

    async def test_record_accept_order_is_save_then_claim(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
    ) -> None:
        """save → record_review (claim) order is essential: only by saving first do
        we have an audit row to compensate when the claim fails."""
        decision = DecisionFactory.build()
        call_order: list[str] = []

        async def _save_side_effect(_action):
            call_order.append("save")

        async def _claim_side_effect(*_a, **_k):
            call_order.append("claim")
            return True

        user_action_repository.save = AsyncMock(side_effect=_save_side_effect)
        decision_repository.record_review = AsyncMock(side_effect=_claim_side_effect)

        await user_action_service.record_accept(actor="curator-1", decision=decision)

        assert call_order == ["save", "claim"]

    async def test_record_reject_claim_lost_compensates_and_raises(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        user_action_repository.save = AsyncMock()
        user_action_repository.delete_by_id = AsyncMock()
        decision_repository.record_review = AsyncMock(return_value=False)

        with pytest.raises(AlreadyCuratedError):
            await user_action_service.record_reject(
                actor="curator-1", decision=decision
            )

        saved_action = user_action_repository.save.await_args.args[0]
        user_action_repository.delete_by_id.assert_awaited_once_with(saved_action.id)

    async def test_record_assign_claim_lost_compensates_and_raises(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        target_cluster = decision.candidates[0].cluster_id
        user_action_repository.save = AsyncMock()
        user_action_repository.delete_by_id = AsyncMock()
        decision_repository.record_review = AsyncMock(return_value=False)

        with pytest.raises(AlreadyCuratedError):
            await user_action_service.record_assign(
                actor="curator-1", decision=decision, cluster_id=target_cluster
            )

        saved_action = user_action_repository.save.await_args.args[0]
        user_action_repository.delete_by_id.assert_awaited_once_with(saved_action.id)


class TestRecordAccept:
    async def test_record_accept_saves_user_action(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        decision_repository.record_review = AsyncMock(return_value=True)

        await user_action_service.record_accept(actor="curator-1", decision=decision)

        user_action_repository.save.assert_called_once()

    async def test_record_accept_already_curated_raises_error(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build(
            updated_at=datetime.now(UTC),
        )
        user_action_repository.delete_by_id = AsyncMock()
        decision_repository.record_review = AsyncMock(return_value=False)

        with pytest.raises(AlreadyCuratedError) as exc_info:
            await user_action_service.record_accept(
                actor="curator-1", decision=decision
            )

        assert exc_info.value.decision_id == decision.id


class TestListUserActions:
    async def test_list_user_actions_returns_cursor_paginated_results(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        entity_mention_repository: MagicMock,
        user_repository: MagicMock,
    ) -> None:
        user = UserFactory.build(id="curator-1")
        action = UserActionFactory.build(actor=user.id)
        entity_mention = EntityMentionFactory.build(
            identifiedBy=action.about_entity_mention,
        )
        expected = CursorPage(results=[action], count=1, next_cursor=None)
        cursor_params = CursorParams(cursor=None, limit=5)
        user_action_repository.find_with_cursor.return_value = expected
        entity_mention_repository.find_by_identifiers.return_value = [entity_mention]
        user_repository.find_by_ids.return_value = [user]

        result = await user_action_service.list_user_actions(cursor_params)

        assert len(result.results) == 1
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
        assert result.results[0].actor.id == user.id
        assert result.results[0].actor.email == user.email
        assert result.next_cursor is None
        user_action_repository.find_with_cursor.assert_called_once_with(
            cursor_params, None
        )
        entity_mention_repository.find_by_identifiers.assert_called_once_with(
            [action.about_entity_mention],
        )
        user_repository.find_by_ids.assert_called_once()


class TestRecordReject:
    async def test_record_reject_saves_user_action(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        decision_repository.record_review = AsyncMock(return_value=True)

        await user_action_service.record_reject(actor="curator-1", decision=decision)

        user_action_repository.save.assert_called_once()


class TestRecordAssign:
    async def test_record_assign_saves_user_action(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        target_id = decision.candidates[0].cluster_id
        decision_repository.record_review = AsyncMock(return_value=True)

        await user_action_service.record_assign(
            actor="curator-1", decision=decision, cluster_id=target_id
        )

        user_action_repository.save.assert_called_once()

    async def test_record_assign_already_curated_raises_error(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        decision_repository: MagicMock,
    ) -> None:
        decision = DecisionFactory.build(
            updated_at=datetime.now(UTC),
        )
        user_action_repository.delete_by_id = AsyncMock()
        decision_repository.record_review = AsyncMock(return_value=False)

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
        user_repository: MagicMock,
    ) -> None:
        user_action_repository.find_with_cursor.return_value = CursorPage(
            results=[],
        )
        entity_mention_repository.find_by_identifiers.return_value = []
        user_repository.find_by_ids.return_value = []
        filters = UserActionFilters(action_type=UserActionType.ACCEPT_TOP)
        cursor_params = CursorParams(limit=10)

        await user_action_service.list_user_actions(cursor_params, filters)

        user_action_repository.find_with_cursor.assert_called_once_with(
            cursor_params, filters
        )

    async def test_filter_by_actor(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        entity_mention_repository: MagicMock,
        user_repository: MagicMock,
    ) -> None:
        user = UserFactory.build(id="user-123")
        action = UserActionFactory.build(actor=user.id)
        user_action_repository.find_with_cursor.return_value = CursorPage(
            results=[action],
        )
        entity_mention_repository.find_by_identifiers.return_value = []
        user_repository.find_by_ids.return_value = [user]
        filters = UserActionFilters(actor=user.id)

        result = await user_action_service.list_user_actions(CursorParams(), filters)

        assert len(result.results) == 1
        assert result.results[0].actor.id == user.id
        assert result.results[0].actor.email == user.email

    async def test_filter_by_time_range(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        entity_mention_repository: MagicMock,
        user_repository: MagicMock,
    ) -> None:
        start = datetime(2026, 3, 13, tzinfo=UTC)
        end = datetime(2026, 3, 20, tzinfo=UTC)
        action = UserActionFactory.build()
        user_action_repository.find_with_cursor.return_value = CursorPage(
            results=[action],
        )
        entity_mention_repository.find_by_identifiers.return_value = []
        user_repository.find_by_ids.return_value = []
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
        user_repository: MagicMock,
    ) -> None:
        user_action_repository.find_with_cursor.return_value = CursorPage(
            results=[],
        )
        entity_mention_repository.find_by_identifiers.return_value = []
        user_repository.find_by_ids.return_value = []

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
        entity_mention_repository.find_by_identifiers.return_value = (
            EntityMentionFactory.batch(2)
        )

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
        entity_mention_repository.find_by_identifiers.return_value = (
            EntityMentionFactory.batch(2)
        )

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
        entity_mention_repository.find_by_identifiers.return_value = (
            EntityMentionFactory.batch(1)
        )

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
        action = UserActionFactory.build(
            candidates=[low, high, mid], selected_cluster=None
        )

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


class TestListUserActionsByDecisionId:
    """Service must resolve decision_id to about_entity_mention before querying repo.

    Phase 3 of TEDSWS-528: the /user-actions endpoint accepts a decision_id
    query parameter.  The service looks up the Decision, extracts its
    about_entity_mention, and passes it as a filter to the repository.
    """

    @pytest.mark.asyncio
    async def test_decision_id_resolved_to_about_entity_mention(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        entity_mention_repository: MagicMock,
        user_repository: MagicMock,
        decision_repository: MagicMock,
    ) -> None:
        """When decision_id is set, the repo receives about_entity_mention in the filter."""
        decision = DecisionFactory.build()
        decision_repository.find_by_id.return_value = decision
        user_action_repository.find_with_cursor.return_value = CursorPage(results=[])
        entity_mention_repository.find_by_identifiers.return_value = []
        user_repository.find_by_ids.return_value = []
        filters = UserActionFilters(decision_id=decision.id)

        await user_action_service.list_user_actions(CursorParams(), filters)

        call_filters = user_action_repository.find_with_cursor.call_args.args[1]
        assert call_filters is not None
        assert call_filters.about_entity_mention == decision.about_entity_mention

    @pytest.mark.asyncio
    async def test_decision_id_resolution_calls_decision_repository(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        entity_mention_repository: MagicMock,
        user_repository: MagicMock,
        decision_repository: MagicMock,
    ) -> None:
        """The service must look up the decision to obtain its entity mention identifier."""
        decision = DecisionFactory.build()
        decision_repository.find_by_id.return_value = decision
        user_action_repository.find_with_cursor.return_value = CursorPage(results=[])
        entity_mention_repository.find_by_identifiers.return_value = []
        user_repository.find_by_ids.return_value = []
        filters = UserActionFilters(decision_id=decision.id)

        await user_action_service.list_user_actions(CursorParams(), filters)

        decision_repository.find_by_id.assert_called_once_with(decision.id)

    @pytest.mark.asyncio
    async def test_no_decision_id_does_not_call_decision_repository(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        entity_mention_repository: MagicMock,
        user_repository: MagicMock,
        decision_repository: MagicMock,
    ) -> None:
        """When decision_id is None the decision repository must not be queried."""
        user_action_repository.find_with_cursor.return_value = CursorPage(results=[])
        entity_mention_repository.find_by_identifiers.return_value = []
        user_repository.find_by_ids.return_value = []
        filters = UserActionFilters(actor="someone")

        await user_action_service.list_user_actions(CursorParams(), filters)

        decision_repository.find_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_decision_id_with_action_type_both_forwarded(
        self,
        user_action_service: UserActionService,
        user_action_repository: MagicMock,
        entity_mention_repository: MagicMock,
        user_repository: MagicMock,
        decision_repository: MagicMock,
    ) -> None:
        """Both about_entity_mention (from decision_id) and action_type are present in
        the filter forwarded to the repository.
        """
        decision = DecisionFactory.build()
        decision_repository.find_by_id.return_value = decision
        user_action_repository.find_with_cursor.return_value = CursorPage(results=[])
        entity_mention_repository.find_by_identifiers.return_value = []
        user_repository.find_by_ids.return_value = []
        filters = UserActionFilters(
            decision_id=decision.id,
            action_type=UserActionType.ACCEPT_TOP,
        )

        await user_action_service.list_user_actions(CursorParams(), filters)

        call_filters = user_action_repository.find_with_cursor.call_args.args[1]
        assert call_filters.about_entity_mention == decision.about_entity_mention
        assert call_filters.action_type == UserActionType.ACCEPT_TOP


class TestRecordReviewOnRecord:
    """record_* methods must call ``decision_repository.record_review`` exactly
    once after a successful action save, passing ``(decision.id,
    user_action.created_at)``.

    The action save is canonical; the materialised primitives (counter + flag)
    are a denormalised mirror updated through ``record_review``. Order matters:
    ``record_review`` is called only after the save succeeds.
    """

    @pytest.fixture
    def decision_repository_mock(self) -> MagicMock:
        mock = create_autospec(DecisionRepository, instance=True)
        # Default to "claim succeeded" so the happy-path tests in this class
        # don't trip the compensation branch. Race-lost behaviour is covered
        # explicitly by TestRaceSafeRecord above.
        mock.record_review = AsyncMock(return_value=True)
        return mock

    @pytest.fixture
    def user_action_service_with_decision_repo(
        self,
        user_action_repository: MagicMock,
        entity_mention_repository: MagicMock,
        user_repository: MagicMock,
        decision_repository_mock: MagicMock,
    ) -> UserActionService:
        return UserActionService(
            user_action_repository=user_action_repository,
            entity_mention_repository=entity_mention_repository,
            user_repository=user_repository,
            decision_repository=decision_repository_mock,
        )

    @staticmethod
    def _saved_action(save_mock: AsyncMock):
        """Return the UserAction handed to ``user_action_repository.save``."""
        assert save_mock.await_count == 1
        return save_mock.await_args.args[0]

    @pytest.mark.asyncio
    async def test_record_accept_calls_record_review_with_action_timestamp(
        self,
        user_action_service_with_decision_repo: UserActionService,
        user_action_repository: MagicMock,
        decision_repository_mock: MagicMock,
    ) -> None:
        """record_accept must call record_review(decision.id, action.created_at)."""
        decision = DecisionFactory.build()
        user_action_repository.has_current_action = AsyncMock(return_value=False)
        user_action_repository.save = AsyncMock()

        await user_action_service_with_decision_repo.record_accept(
            actor="curator-1", decision=decision
        )

        action = self._saved_action(user_action_repository.save)
        decision_repository_mock.record_review.assert_called_once_with(
            decision.id, action.created_at
        )

    @pytest.mark.asyncio
    async def test_record_accept_calls_record_review_after_save(
        self,
        user_action_service_with_decision_repo: UserActionService,
        user_action_repository: MagicMock,
        decision_repository_mock: MagicMock,
    ) -> None:
        """record_review must be called only after the action save succeeds."""
        decision = DecisionFactory.build()
        call_order: list[str] = []
        user_action_repository.has_current_action = AsyncMock(return_value=False)
        user_action_repository.save = AsyncMock(
            side_effect=lambda _: call_order.append("save")
        )

        def _record_review_side_effect(*_args, **_kwargs):
            call_order.append("record_review")
            return True  # claim succeeds → no compensation

        decision_repository_mock.record_review = AsyncMock(
            side_effect=_record_review_side_effect
        )

        await user_action_service_with_decision_repo.record_accept(
            actor="curator-1", decision=decision
        )

        assert call_order == ["save", "record_review"], (
            "record_review must be called after save, not before"
        )

    @pytest.mark.asyncio
    async def test_record_reject_calls_record_review(
        self,
        user_action_service_with_decision_repo: UserActionService,
        user_action_repository: MagicMock,
        decision_repository_mock: MagicMock,
    ) -> None:
        """record_reject must call record_review with the action timestamp."""
        decision = DecisionFactory.build()
        user_action_repository.has_current_action = AsyncMock(return_value=False)
        user_action_repository.save = AsyncMock()

        await user_action_service_with_decision_repo.record_reject(
            actor="curator-1", decision=decision
        )

        action = self._saved_action(user_action_repository.save)
        decision_repository_mock.record_review.assert_called_once_with(
            decision.id, action.created_at
        )

    @pytest.mark.asyncio
    async def test_record_assign_calls_record_review(
        self,
        user_action_service_with_decision_repo: UserActionService,
        user_action_repository: MagicMock,
        decision_repository_mock: MagicMock,
    ) -> None:
        """record_assign must call record_review with the action timestamp."""
        decision = DecisionFactory.build()
        target_id = decision.candidates[0].cluster_id
        user_action_repository.has_current_action = AsyncMock(return_value=False)
        user_action_repository.save = AsyncMock()

        await user_action_service_with_decision_repo.record_assign(
            actor="curator-1", decision=decision, cluster_id=target_id
        )

        action = self._saved_action(user_action_repository.save)
        decision_repository_mock.record_review.assert_called_once_with(
            decision.id, action.created_at
        )

    # NOTE: the previous "record_review must NOT be called when AlreadyCuratedError
    # is raised" test was removed. After the TOCTOU-race fix, ``record_review``
    # IS the atomic idempotency guard — there is no pre-check that could short-
    # circuit before it. The race-lost behaviour (claim returns False → audit
    # row deleted → AlreadyCuratedError raised) is covered in TestRaceSafeRecord
    # at the top of this file.
