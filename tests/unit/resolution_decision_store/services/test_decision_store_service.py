"""Unit tests for DecisionStoreService."""
from datetime import datetime, timezone
from unittest.mock import create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers import config
from ers.commons.domain.cursor import encode_cursor
from ers.commons.domain.data_transfer_objects import CursorPage, CursorParams
from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository
from ers.resolution_decision_store.domain.errors import StaleOutcomeError
from ers.resolution_decision_store.services.decision_store_service import (
    DecisionStoreService,
    get_decision_by_triad,
    query_decisions_paginated,
    store_decision,
)


def make_identifier():
    return EntityMentionIdentifier(source_id="s1", request_id="r1", entity_type="Person")


def make_cluster(cluster_id="c1"):
    return ClusterReference(cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85)


def make_decision(now=None):
    now = now or datetime.now(timezone.utc)
    return Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster(),
        candidates=[],
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def mock_repo():
    return create_autospec(MongoDecisionRepository, instance=True)


@pytest.fixture()
def service(mock_repo):
    return DecisionStoreService(repository=mock_repo)


class TestStoreDecision:
    async def test_delegates_to_repository(self, service, mock_repo):
        now = datetime.now(timezone.utc)
        mock_repo.upsert_decision.return_value = make_decision(now)
        result = await service.store_decision(make_identifier(), make_cluster(), [], now)
        assert isinstance(result, Decision)
        mock_repo.upsert_decision.assert_called_once()

    async def test_truncates_candidates_to_max(self, service, mock_repo):
        now = datetime.now(timezone.utc)
        mock_repo.upsert_decision.return_value = make_decision(now)
        many = [make_cluster(f"c{i}") for i in range(10)]
        await service.store_decision(make_identifier(), make_cluster(), many, now)
        _, kwargs = mock_repo.upsert_decision.call_args
        assert len(kwargs["candidates"]) == config.DECISION_STORE_MAX_CANDIDATES

    async def test_does_not_truncate_when_within_limit(self, service, mock_repo):
        now = datetime.now(timezone.utc)
        mock_repo.upsert_decision.return_value = make_decision(now)
        few = [make_cluster(f"c{i}") for i in range(2)]
        await service.store_decision(make_identifier(), make_cluster(), few, now)
        _, kwargs = mock_repo.upsert_decision.call_args
        assert len(kwargs["candidates"]) == 2

    async def test_propagates_stale_outcome_error(self, service, mock_repo):
        mock_repo.upsert_decision.side_effect = StaleOutcomeError(
            "s1", "r1", "Person", stored_at="T1", attempted_at="T0"
        )
        with pytest.raises(StaleOutcomeError):
            await service.store_decision(
                make_identifier(), make_cluster(), [], datetime.now(timezone.utc)
            )


class TestGetDecisionByTriad:
    async def test_returns_decision_when_found(self, service, mock_repo):
        mock_repo.find_by_triad.return_value = make_decision()
        result = await service.get_decision_by_triad(make_identifier())
        assert isinstance(result, Decision)

    async def test_returns_none_when_not_found(self, service, mock_repo):
        mock_repo.find_by_triad.return_value = None
        result = await service.get_decision_by_triad(make_identifier())
        assert result is None


class TestQueryDecisionsPaginated:
    async def test_returns_cursor_page(self, service, mock_repo):
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)
        result = await service.query_decisions_paginated()
        assert isinstance(result, CursorPage)

    async def test_uses_default_page_size_when_none(self, service, mock_repo):
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)
        await service.query_decisions_paginated(page_size=None)
        _, kwargs = mock_repo.find_with_filters.call_args
        assert kwargs["cursor_params"].limit == config.DECISION_STORE_DEFAULT_PAGE_SIZE

    async def test_caps_page_size_at_system_limit(self, service, mock_repo):
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)
        await service.query_decisions_paginated(page_size=99999)
        _, kwargs = mock_repo.find_with_filters.call_args
        assert kwargs["cursor_params"].limit == config.DECISION_STORE_MAX_PAGE_SIZE

    async def test_passes_cursor_to_repository(self, service, mock_repo):
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)
        cursor = encode_cursor(datetime.now(timezone.utc), "hash123")
        await service.query_decisions_paginated(cursor=cursor)
        _, kwargs = mock_repo.find_with_filters.call_args
        assert kwargs["cursor_params"].cursor == cursor

    async def test_propagates_invalid_cursor_error(self, service, mock_repo):
        from ers.commons.domain.exceptions import InvalidCursorError
        mock_repo.find_with_filters.side_effect = InvalidCursorError()
        with pytest.raises(InvalidCursorError):
            await service.query_decisions_paginated(cursor="bad-cursor-value")


class TestPublicAPIFunctions:
    async def test_store_decision_delegates_to_service(self, service, mock_repo):
        now = datetime.now(timezone.utc)
        mock_repo.upsert_decision.return_value = make_decision(now)
        result = await store_decision(
            make_identifier(), make_cluster(), [], now, service=service
        )
        assert isinstance(result, Decision)

    async def test_get_decision_by_triad_delegates_to_service(self, service, mock_repo):
        mock_repo.find_by_triad.return_value = make_decision()
        result = await get_decision_by_triad(make_identifier(), service=service)
        assert isinstance(result, Decision)

    async def test_query_decisions_paginated_delegates_to_service(self, service, mock_repo):
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)
        result = await query_decisions_paginated(service=service)
        assert isinstance(result, CursorPage)
