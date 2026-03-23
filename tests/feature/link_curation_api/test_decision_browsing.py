"""Step definitions for decision_browsing.feature.

Tests the GET /api/v1/curation/decisions endpoint with filtering, search,
ordering, and pagination through the FastAPI test client.
Repository mocks let real DecisionCurationService logic run end-to-end.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from pytest_bdd import given, parsers, scenario, then, when
from starlette.testclient import TestClient

from ers.commons.domain.data_transfer_objects import CursorPage
from tests.unit.factories import (
    DecisionFactory,
    EntityMentionFactory,
    EntityMentionIdentifierFactory,
)

FEATURE = str(Path(__file__).resolve().parent / "decision_browsing.feature")

DECISIONS_URL = "/api/v1/curation/decisions"

ENTITY_TYPE_MAP = {
    "Organization": "ORGANISATION",
    "Person": "PERSON",
    "Procedure": "PROCEDURE",
}


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario(FEATURE, "List decisions with default parameters")
def test_list_default():
    pass


@scenario(FEATURE, "Decisions default to showing low-confidence items")
def test_default_low_confidence():
    pass


@scenario(FEATURE, "Filter decisions by confidence range")
def test_filter_by_confidence():
    pass


@scenario(FEATURE, "Filter decisions by entity type")
def test_filter_by_entity_type():
    pass


@scenario(FEATURE, "Filter decisions by similarity range")
def test_filter_by_similarity():
    pass


@scenario(FEATURE, "Order decisions by different fields")
def test_order_by_fields():
    pass


@scenario(FEATURE, "Search decisions by entity mention text")
def test_search_by_text():
    pass


@scenario(FEATURE, "Search with no matching results")
def test_search_no_results():
    pass


@scenario(FEATURE, "Navigate through decisions with cursor pagination")
def test_paginate():
    pass


@scenario(FEATURE, "All results fit within the requested limit")
def test_all_results_fit():
    pass


@scenario(FEATURE, "Apply multiple filters simultaneously")
def test_combined_filters():
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_decision_with_mention(decision_id: str = "decision-1"):
    """Create a Decision and a matching EntityMention sharing the same identifier."""
    identifier = EntityMentionIdentifierFactory.build()
    decision = DecisionFactory.build(id=decision_id, about_entity_mention=identifier)
    mention = EntityMentionFactory.build(identifiedBy=identifier)
    return decision, mention


def _setup_decisions(
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
    count: int,
    *,
    prefix: str = "d",
):
    """Wire repository mocks to return *count* decisions with matching mentions."""
    pairs = [_make_decision_with_mention(f"{prefix}-{i}") for i in range(count)]
    decisions = [d for d, _ in pairs]
    mentions = [m for _, m in pairs]

    decision_repository.find_with_filters.return_value = CursorPage(
        results=decisions,
        next_cursor=None,
    )
    entity_mention_repository.find_by_identifiers.return_value = mentions
    return decisions, mentions


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("multiple decisions exist in the decision store")
def multiple_decisions(
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> None:
    _setup_decisions(decision_repository, entity_mention_repository, 3)


@given(
    "decisions exist with confidence scores above and below the curation threshold",
)
def decisions_above_below_threshold(
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> None:
    _setup_decisions(decision_repository, entity_mention_repository, 1, prefix="d-low")


@given("decisions exist with varying confidence scores")
def decisions_varying_confidence(
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> None:
    _setup_decisions(decision_repository, entity_mention_repository, 2)


@given(parsers.parse('decisions exist for entity types "{type_a}" and "{type_b}"'))
def decisions_for_entity_types(
    ctx: dict[str, Any],
    type_a: str,
    type_b: str,
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> None:
    _setup_decisions(decision_repository, entity_mention_repository, 1, prefix="d-org")
    ctx["entity_types"] = (type_a, type_b)


@given("decisions exist with varying similarity scores")
def decisions_varying_similarity(
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> None:
    _setup_decisions(decision_repository, entity_mention_repository, 2)


@given("multiple decisions exist with different timestamps and scores")
def decisions_different_timestamps(
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> None:
    _setup_decisions(decision_repository, entity_mention_repository, 3)


@given("decisions exist linked to entity mentions with various names")
def decisions_with_names(
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> None:
    identifier = EntityMentionIdentifierFactory.build()
    decision = DecisionFactory.build(id="d-acme", about_entity_mention=identifier)
    mention = EntityMentionFactory.build(identifiedBy=identifier)

    entity_mention_repository.search_identifiers.return_value = [identifier]
    decision_repository.find_with_filters.return_value = CursorPage(
        results=[decision],
        next_cursor=None,
    )
    entity_mention_repository.find_by_identifiers.return_value = [mention]


@given("decisions exist in the store")
def decisions_in_store(
    entity_mention_repository: AsyncMock,
) -> None:
    entity_mention_repository.search_identifiers.return_value = []


@given(parsers.parse("{count:d} decisions exist in the store"))
def n_decisions_in_store(
    count: int,
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> None:
    pairs = [_make_decision_with_mention(f"d-{i}") for i in range(count)]
    all_decisions = [d for d, _ in pairs]
    all_mentions = [m for _, m in pairs]

    def _cursor_response(*_args: Any, **kwargs: Any) -> CursorPage:
        cursor_params = kwargs.get("cursor_params")
        limit = cursor_params.limit if cursor_params else 20
        page_items = all_decisions[:limit]
        has_more = count > limit
        return CursorPage(
            results=page_items,
            next_cursor="mock-cursor" if has_more else None,
        )

    decision_repository.find_with_filters.side_effect = _cursor_response
    entity_mention_repository.find_by_identifiers.return_value = all_mentions


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("the curator requests the decision list", target_fixture="response")
def request_decision_list(client: TestClient) -> Any:
    return client.get(DECISIONS_URL)


@when(
    "the curator requests the decision list without specifying confidence filters",
    target_fixture="response",
)
def request_without_confidence(client: TestClient) -> Any:
    return client.get(DECISIONS_URL)


@when(
    parsers.parse(
        "the curator filters decisions with minimum confidence {min_val} "
        "and maximum confidence {max_val}"
    ),
    target_fixture="response",
)
def filter_by_confidence(
    client: TestClient,
    min_val: str,
    max_val: str,
) -> Any:
    return client.get(
        DECISIONS_URL,
        params={"confidence_min": min_val, "confidence_max": max_val},
    )


@when(
    parsers.parse('the curator filters decisions by entity type "{entity_type}"'),
    target_fixture="response",
)
def filter_by_entity_type(client: TestClient, entity_type: str) -> Any:
    return client.get(
        DECISIONS_URL,
        params={"entity_type": ENTITY_TYPE_MAP.get(entity_type, entity_type)},
    )


@when(
    parsers.parse(
        "the curator filters decisions with minimum similarity {min_val} "
        "and maximum similarity {max_val}"
    ),
    target_fixture="response",
)
def filter_by_similarity(
    client: TestClient,
    min_val: str,
    max_val: str,
) -> Any:
    return client.get(
        DECISIONS_URL,
        params={"similarity_min": min_val, "similarity_max": max_val},
    )


@when(
    parsers.parse('the curator requests decisions ordered by "{ordering}"'),
    target_fixture="response",
)
def request_ordered(client: TestClient, ordering: str) -> Any:
    ordering_map = {
        "confidence ascending": "confidence_score",
        "confidence descending": "-confidence_score",
        "created at ascending": "created_at",
        "created at descending": "-created_at",
        "updated at ascending": "updated_at",
        "updated at descending": "-updated_at",
    }
    return client.get(
        DECISIONS_URL,
        params={"ordering": ordering_map[ordering]},
    )


@when(parsers.parse('the curator searches for "{query}"'), target_fixture="response")
def search_decisions(client: TestClient, query: str) -> Any:
    return client.get(DECISIONS_URL, params={"search": query})


@when(
    parsers.parse("the curator requests decisions with a limit of {limit:d}"),
    target_fixture="response",
)
def request_with_limit(client: TestClient, limit: int) -> Any:
    return client.get(
        DECISIONS_URL,
        params={"limit": limit},
    )


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("a paginated list of decision summaries is returned")
def paginated_list_returned(response: Any) -> None:
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "next_cursor" in data


@then(
    "each summary includes the entity mention preview, current placement, and timestamps",
)
def summary_includes_fields(response: Any) -> None:
    for item in response.json()["results"]:
        assert "about_entity_mention" in item
        assert "current_placement" in item
        assert "created_at" in item


@then("only decisions with confidence at or below the threshold are returned")
def only_low_confidence(
    response: Any,
    decision_repository: AsyncMock,
) -> None:
    assert response.status_code == 200
    call_args = decision_repository.find_with_filters.call_args
    filters = call_args.kwargs["filters"]
    assert filters.confidence_max is not None


@then("only decisions within the confidence range are returned")
def confidence_range_applied(
    response: Any,
    decision_repository: AsyncMock,
) -> None:
    assert response.status_code == 200
    call_args = decision_repository.find_with_filters.call_args
    filters = call_args.kwargs["filters"]
    assert filters.confidence_min is not None
    assert filters.confidence_max is not None


@then(parsers.parse('only decisions for "{entity_type}" entities are returned'))
def entity_type_filter_applied(
    response: Any,
    entity_type: str,
    decision_repository: AsyncMock,
) -> None:
    assert response.status_code == 200
    call_args = decision_repository.find_with_filters.call_args
    filters = call_args.kwargs["filters"]
    assert filters.entity_type is not None


@then("only decisions within the similarity range are returned")
def similarity_range_applied(
    response: Any,
    decision_repository: AsyncMock,
) -> None:
    assert response.status_code == 200
    call_args = decision_repository.find_with_filters.call_args
    filters = call_args.kwargs["filters"]
    assert filters.similarity_min is not None
    assert filters.similarity_max is not None


@then("the decisions are returned in the specified order")
def ordering_applied(
    response: Any,
    decision_repository: AsyncMock,
) -> None:
    assert response.status_code == 200
    call_args = decision_repository.find_with_filters.call_args
    filters = call_args.kwargs["filters"]
    assert filters.ordering is not None


@then(parsers.parse('only decisions for entity mentions matching "{query}" are returned'))
def search_applied(
    response: Any,
    query: str,
    entity_mention_repository: AsyncMock,
) -> None:
    assert response.status_code == 200
    entity_mention_repository.search_identifiers.assert_called_once_with(query)


@then("an empty result set is returned")
def empty_results(response: Any) -> None:
    assert response.status_code == 200
    data = response.json()
    assert data["results"] == [] or data["count"] == 0


@then(parsers.parse("{count:d} decision summaries are returned"))
def n_summaries_returned(response: Any, count: int) -> None:
    assert response.status_code == 200
    assert len(response.json()["results"]) == count


@then("a next cursor is provided for further results")
def next_cursor_provided(response: Any) -> None:
    assert response.json()["next_cursor"] is not None


@then("no next cursor is provided")
def no_next_cursor(response: Any) -> None:
    assert response.json()["next_cursor"] is None


# --- Combined filters ---


@given(
    parsers.parse(
        'decisions exist for entity types "{type_a}" and "{type_b}" with varying confidence scores'
    ),
)
def decisions_for_types_with_confidence(
    ctx: dict[str, Any],
    type_a: str,
    type_b: str,
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
) -> None:
    _setup_decisions(decision_repository, entity_mention_repository, 2, prefix="d-combo")
    ctx["entity_types"] = (type_a, type_b)


@when(
    parsers.parse(
        'the curator filters decisions by entity type "{entity_type}" '
        "with maximum confidence {max_conf}"
    ),
    target_fixture="response",
)
def filter_by_type_and_confidence(
    client: TestClient,
    entity_type: str,
    max_conf: str,
) -> Any:
    return client.get(
        DECISIONS_URL,
        params={
            "entity_type": ENTITY_TYPE_MAP.get(entity_type, entity_type),
            "confidence_max": max_conf,
        },
    )


@then(
    parsers.parse(
        'only decisions for "{entity_type}" entities '
        "with confidence at or below {max_conf} are returned"
    ),
)
def combined_filter_applied(
    response: Any,
    entity_type: str,
    max_conf: str,
    decision_repository: AsyncMock,
) -> None:
    assert response.status_code == 200
    call_args = decision_repository.find_with_filters.call_args
    filters = call_args.kwargs["filters"]
    assert filters.entity_type is not None
    assert filters.confidence_max is not None
