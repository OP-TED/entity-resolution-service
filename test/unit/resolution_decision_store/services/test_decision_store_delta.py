"""Unit tests for DecisionStoreService.query_decisions_delta.

Pre-implementation check result: Case B — DecisionFilters in
ers.commons.domain.data_transfer_objects was missing source_id and updated_since.
Both fields were added as optional (None defaults), and _build_query in
MongoDecisionRepository was extended to translate them into MongoDB predicates.
"""
from datetime import UTC, datetime
from unittest.mock import create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers import config
from ers.commons.domain.data_transfer_objects import CursorPage
from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository
from ers.resolution_decision_store.domain.errors import RepositoryConnectionError
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

UTC = UTC


def make_decision(source_id: str = "SRC_A") -> Decision:
    now = datetime.now(UTC)
    identifier = EntityMentionIdentifier(
        source_id=source_id, request_id="req1", entity_type="Person"
    )
    cluster = ClusterReference(cluster_id="c1", confidence_score=0.9, similarity_score=0.85)
    return Decision(
        id="hash123",
        about_entity_mention=identifier,
        current_placement=cluster,
        candidates=[],
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def mock_repo():
    return create_autospec(MongoDecisionRepository, instance=True)


class TestQueryDecisionsDelta:
    async def test_delta_with_snapshot(self, mock_repo):
        svc = DecisionStoreService(repository=mock_repo)
        t0 = datetime(2026, 3, 12, 10, 0, 0, tzinfo=UTC)
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)

        await svc.query_decisions_delta(source_id="SRC_A", updated_since=t0)

        mock_repo.find_with_filters.assert_awaited_once()
        call_kwargs = mock_repo.find_with_filters.call_args.kwargs
        assert call_kwargs["filters"].source_id == "SRC_A"
        assert call_kwargs["filters"].updated_since == t0

    async def test_delta_without_snapshot(self, mock_repo):
        svc = DecisionStoreService(repository=mock_repo)
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)

        await svc.query_decisions_delta(source_id="SRC_B", updated_since=None)

        call_kwargs = mock_repo.find_with_filters.call_args.kwargs
        assert call_kwargs["filters"].source_id == "SRC_B"
        assert call_kwargs["filters"].updated_since is None

    async def test_delta_returns_page(self, mock_repo):
        svc = DecisionStoreService(repository=mock_repo)
        decisions = [make_decision() for _ in range(3)]
        expected_page = CursorPage(results=decisions, next_cursor="tok")
        mock_repo.find_with_filters.return_value = expected_page

        result = await svc.query_decisions_delta(source_id="SRC_A", updated_since=None)

        assert result is expected_page

    async def test_delta_returns_empty_page(self, mock_repo):
        svc = DecisionStoreService(repository=mock_repo)
        empty_page = CursorPage(results=[], next_cursor=None)
        mock_repo.find_with_filters.return_value = empty_page

        result = await svc.query_decisions_delta(source_id="SRC_A", updated_since=None)

        assert result is empty_page
        assert result.results == []
        assert result.next_cursor is None

    async def test_delta_respects_page_size_cap(self, mock_repo):
        svc = DecisionStoreService(repository=mock_repo)
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)

        await svc.query_decisions_delta(
            source_id="SRC_A", updated_since=None, page_size=99999
        )

        call_kwargs = mock_repo.find_with_filters.call_args.kwargs
        assert call_kwargs["cursor_params"].limit == config.DECISION_STORE_MAX_PAGE_SIZE

    async def test_delta_uses_default_page_size(self, mock_repo):
        svc = DecisionStoreService(repository=mock_repo)
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)

        await svc.query_decisions_delta(source_id="SRC_A", updated_since=None)

        call_kwargs = mock_repo.find_with_filters.call_args.kwargs
        assert call_kwargs["cursor_params"].limit == config.DECISION_STORE_DEFAULT_PAGE_SIZE

    async def test_delta_passes_cursor(self, mock_repo):
        svc = DecisionStoreService(repository=mock_repo)
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)

        await svc.query_decisions_delta(
            source_id="SRC_A", updated_since=None, cursor="opaque-token"
        )

        call_kwargs = mock_repo.find_with_filters.call_args.kwargs
        assert call_kwargs["cursor_params"].cursor == "opaque-token"

    async def test_delta_propagates_connection_error(self, mock_repo):
        svc = DecisionStoreService(repository=mock_repo)
        mock_repo.find_with_filters.side_effect = RepositoryConnectionError("MongoDB down")

        with pytest.raises(RepositoryConnectionError):
            await svc.query_decisions_delta(source_id="SRC_A", updated_since=None)
