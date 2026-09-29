"""Step definitions for: paginated_query.feature"""
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from pytest_bdd import given, scenario, then, when

from ers import config
from ers.commons.domain.cursor import encode_cursor
from ers.commons.domain.data_transfer_objects import CursorPage
from ers.commons.domain.exceptions import InvalidCursorError
from ers.resolution_decision_store.services.decision_store_service import query_decisions_paginated

FEATURE_FILE = str(Path(__file__).parent / "paginated_query.feature")


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE_FILE, "First page with no cursor returns results and a next cursor")
def test_first_page_with_no_cursor():
    pass


@scenario(FEATURE_FILE, "Following the cursor returns remaining decisions")
def test_following_cursor():
    pass


@scenario(FEATURE_FILE, "Empty store returns empty page")
def test_empty_store_empty_page():
    pass


@scenario(FEATURE_FILE, "page_size is capped at system limit")
def test_page_size_capped():
    pass


@scenario(FEATURE_FILE, "Querying with a malformed cursor raises an error")
def test_malformed_cursor_rejected():
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_identifier(source_id="s1", request_id="r1", entity_type="Person"):
    return EntityMentionIdentifier(
        source_id=source_id, request_id=request_id, entity_type=entity_type
    )


def make_cluster(cluster_id="c1"):
    return ClusterReference(
        cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85
    )


def make_decision(now, source_id="s1"):
    return Decision(
        id=f"hash_{source_id}",
        about_entity_mention=make_identifier(source_id=source_id),
        current_placement=make_cluster(),
        candidates=[],
        created_at=now,
        updated_at=now,
    )


def build_decisions(count=5):
    base = datetime.now(UTC)
    return [
        make_decision(base + timedelta(seconds=i), source_id=f"s{i}")
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("5 stored decisions")
def step_5_stored_decisions(ctx):
    ctx["decisions"] = build_decisions(5)


@given("an empty decision store")
def step_empty_store(ctx, mock_repo):
    ctx["decisions"] = []
    mock_repo.find_with_filters = AsyncMock(
        return_value=CursorPage(results=[], next_cursor=None)
    )


@given("a valid decision store")
def step_valid_store(ctx):
    ctx["decisions"] = build_decisions(5)


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("I query decisions with page_size 3 and no cursor")
def step_query_page1(ctx, service, mock_repo):
    decisions = ctx["decisions"]
    mock_repo.find_with_filters = AsyncMock(
        return_value=CursorPage(
            results=decisions[:3],
            next_cursor=encode_cursor(decisions[2].updated_at, decisions[2].id),
        )
    )
    try:
        ctx["page1"] = asyncio.run(
            query_decisions_paginated(service=service, page_size=3)
        )
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["page1"] = None
        ctx["raised_exception"] = exc


@when("I query page 1 then follow the next_cursor")
def step_query_follow_cursor(ctx, service, mock_repo):
    decisions = ctx["decisions"]
    mock_repo.find_with_filters = AsyncMock(
        side_effect=[
            CursorPage(
                results=decisions[:3],
                next_cursor=encode_cursor(decisions[2].updated_at, decisions[2].id),
            ),
            CursorPage(results=decisions[3:], next_cursor=None),
        ]
    )
    try:
        page1 = asyncio.run(query_decisions_paginated(service=service, page_size=3))
        ctx["page2"] = asyncio.run(
            query_decisions_paginated(service=service, page_size=3, cursor=page1.next_cursor)
        )
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["page2"] = None
        ctx["raised_exception"] = exc


@when("I query decisions paginated")
def step_query_paginated_empty(ctx, service):
    try:
        ctx["result"] = asyncio.run(query_decisions_paginated(service=service))
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["result"] = None
        ctx["raised_exception"] = exc


@when("I query decisions with a malformed cursor")
def step_query_malformed_cursor(ctx, service, mock_repo):
    mock_repo.find_with_filters = AsyncMock(side_effect=InvalidCursorError())
    try:
        asyncio.run(query_decisions_paginated(service=service, cursor="not!!valid-base64"))
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["raised_exception"] = exc


@when("I query with page_size 9999")
def step_query_large_page_size(ctx, service, mock_repo):
    mock_repo.find_with_filters = AsyncMock(
        return_value=CursorPage(results=ctx["decisions"][:3], next_cursor=None)
    )
    try:
        asyncio.run(query_decisions_paginated(service=service, page_size=9999))
        ctx["call_args"] = mock_repo.find_with_filters.call_args
        ctx["raised_exception"] = None
    except Exception as exc:
        ctx["call_args"] = None
        ctx["raised_exception"] = exc


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("I receive 3 records")
def step_receive_3_records(ctx):
    assert ctx["raised_exception"] is None, ctx["raised_exception"]
    assert len(ctx["page1"].results) == 3


@then("the response includes a next_cursor")
def step_next_cursor_present(ctx):
    assert ctx["page1"].next_cursor is not None


@then("page 2 contains 2 records with no next_cursor")
def step_page2_2_records_no_cursor(ctx):
    assert ctx["raised_exception"] is None, ctx["raised_exception"]
    assert len(ctx["page2"].results) == 2
    assert ctx["page2"].next_cursor is None


@then("I receive 0 records and no next_cursor")
def step_empty_page(ctx):
    assert ctx["raised_exception"] is None, ctx["raised_exception"]
    assert len(ctx["result"].results) == 0
    assert ctx["result"].next_cursor is None


@then("the effective page_size does not exceed the system maximum page size")
def step_page_size_capped(ctx):
    assert ctx["raised_exception"] is None, ctx["raised_exception"]
    effective_limit = ctx["call_args"].kwargs["cursor_params"].limit
    assert effective_limit <= config.DECISION_STORE_MAX_PAGE_SIZE


@then("an InvalidCursorError is raised")
def step_invalid_cursor_error_raised(ctx):
    assert isinstance(ctx["raised_exception"], InvalidCursorError)
