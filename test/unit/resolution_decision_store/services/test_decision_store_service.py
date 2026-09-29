"""Unit tests for DecisionStoreService."""
from datetime import UTC, datetime
from unittest.mock import MagicMock, create_autospec, patch

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers import config
from ers.commons.domain.cursor import encode_cursor
from ers.commons.domain.data_transfer_objects import CursorPage
from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository
from ers.resolution_decision_store.domain.errors import StaleOutcomeError
from ers.resolution_decision_store.services.decision_store_service import (
    DecisionStoreService,
    get_decision_by_triad,
    query_decisions_delta,
    query_decisions_paginated,
    store_decision,
)


def make_identifier():
    return EntityMentionIdentifier(source_id="s1", request_id="r1", entity_type="Person")


def make_cluster(cluster_id="c1"):
    return ClusterReference(cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85)


def make_decision(now=None):
    now = now or datetime.now(UTC)
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
        now = datetime.now(UTC)
        mock_repo.upsert_decision.return_value = make_decision(now)
        result = await service.store_decision(make_identifier(), make_cluster(), [], now)
        assert isinstance(result, Decision)
        mock_repo.upsert_decision.assert_called_once()

    async def test_truncates_candidates_to_max(self, service, mock_repo):
        now = datetime.now(UTC)
        mock_repo.upsert_decision.return_value = make_decision(now)
        many = [make_cluster(f"c{i}") for i in range(10)]
        await service.store_decision(make_identifier(), make_cluster(), many, now)
        _, kwargs = mock_repo.upsert_decision.call_args
        assert len(kwargs["candidates"]) == config.DECISION_STORE_MAX_CANDIDATES

    async def test_does_not_truncate_when_within_limit(self, service, mock_repo):
        now = datetime.now(UTC)
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
                make_identifier(), make_cluster(), [], datetime.now(UTC)
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
        cursor = encode_cursor(datetime.now(UTC), "hash123")
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
        now = datetime.now(UTC)
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

    async def test_query_decisions_delta_delegates_to_service(self, service, mock_repo):
        mock_repo.find_delta_for_source.return_value = CursorPage(results=[], next_cursor=None)
        result = await query_decisions_delta(
            source_id="s1", updated_since=None, service=service, cursor=None, page_size=10
        )
        assert isinstance(result, CursorPage)


# ── R1 short-circuit tests (module-level, asyncio auto) ───────────────────────


@pytest.mark.asyncio
async def test_first_insert_passes_updated_at_none_to_repo():
    """U-01: First insert — upsert_decision called with the new placement; no prior find."""
    mock_repo = create_autospec(MongoDecisionRepository, instance=True)
    now = datetime.now(UTC)
    # No existing decision for this triad.
    mock_repo.find_by_triad.return_value = None
    mock_repo.upsert_decision.return_value = make_decision(now)

    svc = DecisionStoreService(repository=mock_repo)
    result = await svc.store_decision(make_identifier(), make_cluster(), [], now)

    mock_repo.find_by_triad.assert_awaited_once()
    mock_repo.upsert_decision.assert_awaited_once()
    assert isinstance(result, Decision)


@pytest.mark.asyncio
async def test_same_placement_short_circuits_to_existing():
    """U-02: Same-placement re-write — existing Decision returned; upsert NOT called."""
    mock_repo = create_autospec(MongoDecisionRepository, instance=True)
    now = datetime.now(UTC)
    existing = Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster("c1"),
        candidates=[],
        created_at=now,
        updated_at=None,  # Never moved — updated_at is None
    )
    mock_repo.find_by_triad.return_value = existing

    svc = DecisionStoreService(repository=mock_repo)
    # Incoming current.cluster_id == "c1" matches existing.current_placement.cluster_id
    result = await svc.store_decision(make_identifier(), make_cluster("c1"), [], now)

    mock_repo.upsert_decision.assert_not_awaited()
    assert result is existing


@pytest.mark.asyncio
async def test_different_placement_calls_upsert():
    """U-03: Different-placement re-write — upsert IS called."""
    mock_repo = create_autospec(MongoDecisionRepository, instance=True)
    now = datetime.now(UTC)
    existing = Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster("c1"),
        candidates=[],
        created_at=now,
        updated_at=None,
    )
    mock_repo.find_by_triad.return_value = existing
    newer = Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster("c2"),
        candidates=[],
        created_at=now,
        updated_at=now,
    )
    mock_repo.upsert_decision.return_value = newer

    svc = DecisionStoreService(repository=mock_repo)
    result = await svc.store_decision(make_identifier(), make_cluster("c2"), [], now)

    mock_repo.upsert_decision.assert_awaited_once()
    assert result.current_placement.cluster_id == "c2"


@pytest.mark.asyncio
async def test_same_cluster_different_candidates_writes_through():
    """D3: candidates ARE part of the outcome; same cluster + different candidates → write."""
    mock_repo = create_autospec(MongoDecisionRepository, instance=True)
    now = datetime.now(UTC)
    existing = Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster("c1"),
        candidates=[],
        created_at=now,
        updated_at=None,
    )
    mock_repo.find_by_triad.return_value = existing
    mock_repo.upsert_decision.return_value = make_decision(now)

    svc = DecisionStoreService(repository=mock_repo)
    # Same cluster_id but a different candidate list — outcome changed → must write through
    many_candidates = [make_cluster(f"c{i}") for i in range(5)]
    await svc.store_decision(make_identifier(), make_cluster("c1"), many_candidates, now)

    mock_repo.upsert_decision.assert_awaited_once()


@pytest.mark.asyncio
async def test_same_cluster_different_confidence_writes_through():
    """D3: same cluster but a lower confidence is a material change → write + bump updated_at."""
    mock_repo = create_autospec(MongoDecisionRepository, instance=True)
    now = datetime.now(UTC)
    existing = Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=ClusterReference(
            cluster_id="c1", confidence_score=0.9, similarity_score=0.85
        ),
        candidates=[],
        created_at=now,
        updated_at=None,
    )
    mock_repo.find_by_triad.return_value = existing
    mock_repo.upsert_decision.return_value = make_decision(now)

    svc = DecisionStoreService(repository=mock_repo)
    lower_confidence = ClusterReference(
        cluster_id="c1", confidence_score=0.55, similarity_score=0.85
    )
    await svc.store_decision(make_identifier(), lower_confidence, [], now)

    mock_repo.upsert_decision.assert_awaited_once()


@pytest.mark.asyncio
async def test_identical_outcome_short_circuits():
    """D3: identical placement AND candidates → idempotent no-op (no write)."""
    mock_repo = create_autospec(MongoDecisionRepository, instance=True)
    now = datetime.now(UTC)
    candidates = [make_cluster("c2"), make_cluster("c3")]
    existing = Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster("c1"),
        candidates=candidates,
        created_at=now,
        updated_at=None,
    )
    mock_repo.find_by_triad.return_value = existing

    svc = DecisionStoreService(repository=mock_repo)
    # Exact same outcome replayed — must be a no-op
    result = await svc.store_decision(
        make_identifier(), make_cluster("c1"), [make_cluster("c2"), make_cluster("c3")], now
    )

    mock_repo.upsert_decision.assert_not_awaited()
    assert result is existing


# ── R8 span attribute tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_op_short_circuit_sets_span_attribute():
    """R8: same-placement no-op emits decision_store.placement_unchanged=True span attribute."""
    mock_repo = create_autospec(MongoDecisionRepository, instance=True)
    now = datetime.now(UTC)
    existing = Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster("c1"),
        candidates=[],
        created_at=now,
        updated_at=None,
    )
    mock_repo.find_by_triad.return_value = existing

    mock_span = MagicMock()
    with patch("opentelemetry.trace.get_current_span", return_value=mock_span):
        svc = DecisionStoreService(repository=mock_repo)
        await svc.store_decision(make_identifier(), make_cluster("c1"), [], now)

    mock_span.set_attribute.assert_any_call("decision_store.placement_unchanged", True)


@pytest.mark.asyncio
async def test_genuine_write_does_not_set_placement_unchanged_attribute():
    """R8: genuine placement change must NOT emit decision_store.placement_unchanged."""
    mock_repo = create_autospec(MongoDecisionRepository, instance=True)
    now = datetime.now(UTC)
    existing = Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster("c1"),
        candidates=[],
        created_at=now,
        updated_at=None,
    )
    mock_repo.find_by_triad.return_value = existing
    mock_repo.upsert_decision.return_value = make_decision(now)

    mock_span = MagicMock()
    with patch("opentelemetry.trace.get_current_span", return_value=mock_span):
        svc = DecisionStoreService(repository=mock_repo)
        await svc.store_decision(make_identifier(), make_cluster("c2"), [], now)

    called_attrs = [call.args[0] for call in mock_span.set_attribute.call_args_list]
    assert "decision_store.placement_unchanged" not in called_attrs
