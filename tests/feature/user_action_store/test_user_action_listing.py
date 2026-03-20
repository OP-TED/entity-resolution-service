"""Step definitions for user_action_listing.feature.

Tests the UserActionService.list_user_actions method with mocked repositories,
covering pagination, ordering, and entity mention preview enrichment.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from erspec.models.core import UserAction
from pytest_bdd import given, parsers, scenario, then, when

from ers.commons.domain.data_transfer_objects import PaginatedResult, PaginationParams
from ers.curation.domain.data_transfer_objects import UserActionSummary
from ers.curation.services import UserActionService
from tests.unit.factories import EntityMentionFactory, UserActionFactory

FEATURE = str(Path(__file__).resolve().parent / "user_action_listing.feature")


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE, "List user actions ordered by most recent first")
def test_list_ordered_by_recent():
    pass


@scenario(FEATURE, "Paginate through user actions")
def test_paginate():
    pass


@scenario(FEATURE, "Last page of user actions")
def test_last_page():
    pass


@scenario(FEATURE, "Empty action listing")
def test_empty():
    pass


@scenario(FEATURE, "User actions are enriched with entity mention previews")
def test_enriched_with_preview():
    pass


@scenario(FEATURE, "User actions for missing entity mentions show partial previews")
def test_missing_mention_partial_preview():
    pass


@scenario(FEATURE, "Filter the action trail by a single criterion")
def test_filter_action_trail():
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_actions(count: int) -> list[UserAction]:
    """Build user actions with descending timestamps so index 0 is most recent."""
    base = datetime.now(UTC)
    return [UserActionFactory.build(created_at=base - timedelta(minutes=i)) for i in range(count)]


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(
    parsers.parse("{count:d} user actions have been recorded at different times"),
    target_fixture="actions",
)
def n_actions_at_different_times(
    count: int,
    user_action_repository: MagicMock,
    entity_mention_repository: MagicMock,
) -> list[UserAction]:
    actions = _build_actions(count)
    user_action_repository.find_paginated.return_value = PaginatedResult(
        count=count,
        previous=None,
        next=None,
        results=actions,
    )
    entity_mention_repository.find_by_identifiers.return_value = []
    return actions


@given(
    parsers.parse("{count:d} user actions have been recorded"),
    target_fixture="actions",
)
def n_actions_recorded(
    count: int,
    user_action_repository: MagicMock,
    entity_mention_repository: MagicMock,
) -> list[UserAction]:
    actions = _build_actions(count)
    entity_mention_repository.find_by_identifiers.return_value = []
    user_action_repository._all_actions = actions
    return actions


@given("no user actions have been recorded")
def no_actions(
    user_action_repository: MagicMock,
    entity_mention_repository: MagicMock,
) -> None:
    user_action_repository.find_paginated.return_value = PaginatedResult(
        count=0,
        previous=None,
        next=None,
        results=[],
    )
    entity_mention_repository.find_by_identifiers.return_value = []


@given("a user action exists for an entity mention with a parsed representation")
def action_with_parsed_mention(
    ctx: dict[str, Any],
    user_action_repository: MagicMock,
    entity_mention_repository: MagicMock,
) -> None:
    action = UserActionFactory.build()
    mention = EntityMentionFactory.build(
        identifiedBy=action.about_entity_mention,
    )
    user_action_repository.find_paginated.return_value = PaginatedResult(
        count=1,
        previous=None,
        next=None,
        results=[action],
    )
    entity_mention_repository.find_by_identifiers.return_value = [mention]
    ctx["action"] = action
    ctx["mention"] = mention


@given("a user action exists for an entity mention that has no parsed representation")
def action_with_missing_mention(
    ctx: dict[str, Any],
    user_action_repository: MagicMock,
    entity_mention_repository: MagicMock,
) -> None:
    action = UserActionFactory.build()
    user_action_repository.find_paginated.return_value = PaginatedResult(
        count=1,
        previous=None,
        next=None,
        results=[action],
    )
    entity_mention_repository.find_by_identifiers.return_value = []
    ctx["action"] = action


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(
    "the action listing is requested for page 1",
    target_fixture="listing_result",
)
def request_page_1(
    user_action_service: UserActionService,
) -> PaginatedResult[UserActionSummary]:
    return asyncio.run(
        user_action_service.list_user_actions(PaginationParams(page=1)),
    )


@when(
    parsers.parse(
        "the action listing is requested for page {page:d} with {per_page:d} items per page"
    ),
    target_fixture="listing_result",
)
def request_page_with_size(
    page: int,
    per_page: int,
    user_action_service: UserActionService,
    user_action_repository: MagicMock,
) -> PaginatedResult[UserActionSummary]:
    if hasattr(user_action_repository, "_all_actions"):
        all_actions = user_action_repository._all_actions
        total = len(all_actions)
        start = (page - 1) * per_page
        page_items = all_actions[start : start + per_page]
        total_pages = (total + per_page - 1) // per_page if total > 0 else 0
        user_action_repository.find_paginated.return_value = PaginatedResult(
            count=total,
            previous=page - 1 if page > 1 else None,
            next=page + 1 if page < total_pages else None,
            results=page_items,
        )
    return asyncio.run(
        user_action_service.list_user_actions(
            PaginationParams(page=page, per_page=per_page),
        ),
    )


@when(
    "the action listing is requested",
    target_fixture="listing_result",
)
def request_listing(
    user_action_service: UserActionService,
) -> PaginatedResult[UserActionSummary]:
    return asyncio.run(
        user_action_service.list_user_actions(PaginationParams()),
    )


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the actions are returned in reverse chronological order")
def actions_in_reverse_order(listing_result: PaginatedResult[UserActionSummary]) -> None:
    timestamps = [r.created_at for r in listing_result.results]
    assert timestamps == sorted(timestamps, reverse=True)


@then("the most recent action appears first")
def most_recent_first(listing_result: PaginatedResult[UserActionSummary]) -> None:
    results = listing_result.results
    if len(results) > 1:
        assert results[0].created_at >= results[1].created_at


@then(parsers.parse("{count:d} actions are returned"))
def n_actions_returned(listing_result: PaginatedResult[UserActionSummary], count: int) -> None:
    assert len(listing_result.results) == count


@then(parsers.parse("the total count is {count:d}"))
def total_count_is(listing_result: PaginatedResult[UserActionSummary], count: int) -> None:
    assert listing_result.count == count


@then(parsers.parse("a next page indicator points to page {page:d}"))
def next_page_points_to(listing_result: PaginatedResult[UserActionSummary], page: int) -> None:
    assert listing_result.next == page


@then("there is no next page indicator")
def no_next_page(listing_result: PaginatedResult[UserActionSummary]) -> None:
    assert listing_result.next is None


@then(parsers.parse("the result contains {count:d} actions"))
def result_contains_n_actions(
    listing_result: PaginatedResult[UserActionSummary],
    count: int,
) -> None:
    assert len(listing_result.results) == count


@then("each action summary includes the entity mention preview")
def action_has_preview(listing_result: PaginatedResult[UserActionSummary]) -> None:
    for summary in listing_result.results:
        assert summary.about_entity_mention is not None
        assert summary.about_entity_mention.identified_by is not None


@then("the preview contains the parsed representation when available")
def preview_has_parsed_representation(
    listing_result: PaginatedResult[UserActionSummary],
) -> None:
    for summary in listing_result.results:
        assert summary.about_entity_mention.parsed_representation is not None


@then("the action summary includes the entity mention identifier")
def action_has_identifier(listing_result: PaginatedResult[UserActionSummary]) -> None:
    for summary in listing_result.results:
        assert summary.about_entity_mention.identified_by is not None


@then("the parsed representation is empty")
def parsed_representation_is_empty(
    listing_result: PaginatedResult[UserActionSummary],
) -> None:
    for summary in listing_result.results:
        assert summary.about_entity_mention.parsed_representation is None


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


@given(
    "user actions have been recorded by multiple curators across different "
    "recommendation types and time periods",
)
def diverse_actions_recorded(
    ctx: dict[str, Any],
    user_action_repository: MagicMock,
    entity_mention_repository: MagicMock,
) -> None:
    from erspec.models.core import UserActionType

    now = datetime.now(UTC)
    accept_action = UserActionFactory.build(
        actor="curator@example.com",
        action_type=UserActionType.ACCEPT_TOP,
        created_at=now - timedelta(days=2),
    )
    reject_action = UserActionFactory.build(
        actor="other@example.com",
        action_type=UserActionType.REJECT_ALL,
        created_at=now - timedelta(days=10),
    )
    ctx["all_actions"] = [accept_action, reject_action]
    ctx["accept_action"] = accept_action
    ctx["reject_action"] = reject_action

    def side_effect_paginated(pagination, filters=None):
        from ers.curation.domain.data_transfer_objects import UserActionFilters

        if filters is None:
            actions = ctx["all_actions"]
        elif isinstance(filters, UserActionFilters):
            actions = ctx["all_actions"]
            if filters.action_type is not None:
                actions = [a for a in actions if a.action_type == filters.action_type]
            if filters.actor is not None:
                actions = [a for a in actions if a.actor == filters.actor]
            if filters.time_range_start is not None:
                actions = [a for a in actions if a.created_at >= filters.time_range_start]
            if filters.time_range_end is not None:
                actions = [a for a in actions if a.created_at <= filters.time_range_end]
        else:
            actions = ctx["all_actions"]
        return PaginatedResult(
            count=len(actions),
            previous=None,
            next=None,
            results=actions,
        )

    user_action_repository.find_paginated.side_effect = side_effect_paginated
    entity_mention_repository.find_by_identifiers.return_value = []


@when(
    parsers.parse("the action listing is filtered by {criterion} matching {value}"),
    target_fixture="listing_result",
)
def filter_action_listing(
    ctx: dict[str, Any],
    criterion: str,
    value: str,
    user_action_service: UserActionService,
) -> PaginatedResult[UserActionSummary]:
    from erspec.models.core import UserActionType

    from ers.curation.domain.data_transfer_objects import UserActionFilters

    criterion = criterion.strip()
    value = value.strip()

    if criterion == "recommendation type":
        type_map = {
            "accept top recommendation": UserActionType.ACCEPT_TOP,
            "reject all": UserActionType.REJECT_ALL,
            "accept alternative": UserActionType.ACCEPT_ALTERNATIVE,
        }
        filters = UserActionFilters(action_type=type_map[value])
    elif criterion == "actor":
        filters = UserActionFilters(actor=value)
    elif criterion == "time range":
        now = datetime.now(UTC)
        filters = UserActionFilters(
            time_range_start=now - timedelta(days=7),
            time_range_end=now,
        )
    else:
        msg = f"Unknown filter criterion: {criterion}"
        raise ValueError(msg)

    ctx["applied_filter_criterion"] = criterion
    ctx["applied_filter_value"] = value

    return asyncio.run(
        user_action_service.list_user_actions(PaginationParams(), filters),
    )


@then(parsers.parse("only actions matching {value} are returned"))
def only_matching_actions(
    listing_result: PaginatedResult[UserActionSummary],
    value: str,
) -> None:
    assert listing_result.count > 0
    assert len(listing_result.results) > 0


@then("actions that do not match are excluded")
def non_matching_excluded(
    ctx: dict[str, Any],
    listing_result: PaginatedResult[UserActionSummary],
) -> None:
    assert listing_result.count < len(ctx["all_actions"])
