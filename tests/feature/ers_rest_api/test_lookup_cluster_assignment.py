"""
Step definitions for: lookup_cluster_assignment.feature

Feature: Cluster Assignment Lookup via REST API (Spine C)
  Covers single-mention GET /api/v1/lookup and bulk POST /api/v1/refresh-bulk:

  Single-mention lookup (GET /api/v1/lookup):
    1. Known mention — returns cluster reference and last_updated (Outline).
    2. Unknown mention triad → 404.
    3. Missing or empty query parameters → 400 (Outline).

  Bulk lookup / refresh-bulk (POST /api/v1/refresh-bulk):
    4. Changed assignments since last synchronisation snapshot (Outline).
    5. First-ever bulk lookup — returns all assignments.
    6. Pagination walk — cursor-based navigation until exhausted.
    7. Default page size when limit is omitted.
    8. Invalid request fields → 400 (Outline).

  Service failures:
    9.  Lookup service raises RuntimeError → 500.
    10. Refresh-bulk service raises RuntimeError → 500.

  Read-only contract:
    11. Neither endpoint modifies assignments or triggers resolution.

Background Given steps ("the ERS REST API is running", "the Decision Store
is available") and common Then steps are defined in conftest.py.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from erspec.models.core import ClusterReference, EntityMentionIdentifier
from pytest_bdd import given, parsers, scenario, then, when

from ers.ers_rest_api.domain.lookup import LookupResponse, RefreshBulkResponse
from ers.ers_rest_api.services.exceptions import MentionNotFoundError
from tests.feature.ers_rest_api.conftest import _make_client, run_async

# ---------------------------------------------------------------------------
# Feature file binding
# ---------------------------------------------------------------------------

FEATURE_FILE = str(Path(__file__).parent / "lookup_cluster_assignment.feature")


# ---------------------------------------------------------------------------
# Scenario bindings — single-mention lookup
# ---------------------------------------------------------------------------


@scenario(FEATURE_FILE, "Look up current assignment for a known mention")
def test_lookup_known_mention():
    pass


@scenario(FEATURE_FILE, "Return not found when the mention triad is unknown")
def test_lookup_unknown_mention():
    pass


@scenario(FEATURE_FILE, "Reject single lookup with missing or empty query parameters")
def test_lookup_missing_or_empty_params():
    pass


# ---------------------------------------------------------------------------
# Scenario bindings — bulk lookup (refresh-bulk)
# ---------------------------------------------------------------------------


@scenario(
    FEATURE_FILE,
    "Retrieve changed assignments since the last synchronisation snapshot",
)
def test_bulk_changed_assignments():
    pass


@scenario(
    FEATURE_FILE,
    "First bulk lookup for a source returns all assignments",
)
def test_bulk_first_call():
    pass


@scenario(FEATURE_FILE, "Page through a large delta set until exhausted")
def test_bulk_pagination_walk():
    pass


@scenario(FEATURE_FILE, "Default page size is applied when limit is omitted")
def test_bulk_default_limit():
    pass


@scenario(FEATURE_FILE, "Reject bulk lookup with invalid request fields")
def test_bulk_invalid_fields():
    pass


# ---------------------------------------------------------------------------
# Scenario bindings — service failures
# ---------------------------------------------------------------------------


@scenario(
    FEATURE_FILE,
    "Return service error when Decision Store is unavailable for single lookup",
)
def test_lookup_decision_store_unavailable():
    pass


@scenario(
    FEATURE_FILE,
    "Return service error on bulk lookup",
)
def test_bulk_decision_store_error():
    pass


# ---------------------------------------------------------------------------
# Scenario bindings — read-only contract
# ---------------------------------------------------------------------------


@scenario(
    FEATURE_FILE,
    "Lookup operations do not modify assignments or trigger resolution",
)
def test_read_only_contract():
    pass


# ---------------------------------------------------------------------------
# Helper — build a minimal LookupResponse
# ---------------------------------------------------------------------------


def _make_lookup_response(
    source_id: str,
    request_id: str,
    entity_type: str,
    cluster_id: str,
    last_updated: datetime,
) -> LookupResponse:
    """Build a LookupResponse with the given fields.

    Args:
        source_id: Source system identifier.
        request_id: Request identifier.
        entity_type: Entity type string.
        cluster_id: Cluster identifier string.
        last_updated: Timestamp of the last assignment update.

    Returns:
        A fully populated LookupResponse.
    """
    return LookupResponse(
        identified_by=EntityMentionIdentifier(
            source_id=source_id,
            request_id=request_id,
            entity_type=entity_type,
        ),
        cluster_reference=ClusterReference(
            cluster_id=cluster_id,
            confidence_score=0.9,
            similarity_score=0.85,
        ),
        last_updated=last_updated,
    )


# ---------------------------------------------------------------------------
# Given — single-mention lookup
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        'a mention with triad "{source_id}", "{request_id}", '
        '"{entity_type}" exists in the Decision Store'
    )
)
def mention_exists_in_decision_store(ctx, source_id, request_id, entity_type):
    """Record the triad for a mention that exists in the Decision Store.

    The cluster assignment is configured by the following Given step.

    Args:
        ctx: Shared mutable step context.
        source_id: Source system identifier.
        request_id: Request identifier.
        entity_type: Entity type string.
    """
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = entity_type


@given(
    parsers.parse(
        'the current cluster assignment is "{cluster_id}" last updated at "{last_updated}"'
    )
)
def cluster_assignment_with_timestamp(ctx, cluster_id, last_updated):
    """Configure the lookup service mock to return the given cluster assignment.

    Args:
        ctx: Shared mutable step context.
        cluster_id: Cluster identifier to return.
        last_updated: ISO 8601 timestamp string for the last update.
    """
    ctx["cluster_id"] = cluster_id
    ctx["last_updated"] = last_updated

    ctx["lookup_service"].handle_lookup = AsyncMock(
        return_value=_make_lookup_response(
            source_id=ctx["source_id"],
            request_id=ctx["request_id"],
            entity_type=ctx["entity_type"],
            cluster_id=cluster_id,
            last_updated=datetime.fromisoformat(last_updated),
        )
    )


@given(
    parsers.parse(
        'no mention with triad "{source_id}", "{request_id}", '
        '"{entity_type}" exists in the Decision Store'
    )
)
def mention_not_in_decision_store(ctx, source_id, request_id, entity_type):
    """Configure the lookup service mock to raise MentionNotFoundError.

    Args:
        ctx: Shared mutable step context.
        source_id: Source system identifier.
        request_id: Request identifier.
        entity_type: Entity type string.
    """
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = entity_type

    ctx["lookup_service"].handle_lookup = AsyncMock(
        side_effect=MentionNotFoundError(source_id, request_id, entity_type)
    )


@given(parsers.parse("a GET /api/v1/lookup request with {param_condition}"))
def lookup_with_param_condition(ctx, param_condition):
    """Build query params dict based on the condition (absent or empty).

    Args:
        ctx: Shared mutable step context.
        param_condition: Description of which parameter is absent or empty.
    """
    base = {
        "source_id": "SYSTEM_X",
        "request_id": "req-001",
        "entity_type": "ORGANISATION",
    }
    if "absent" in param_condition:
        field = param_condition.replace(" absent", "").strip()
        base.pop(field, None)
    elif "set to empty" in param_condition:
        field = param_condition.replace(" set to empty", "").strip()
        base[field] = ""
    ctx["query_params"] = base


@given("the lookup service raises a runtime error")
def lookup_service_raises_error(ctx):
    """Configure the lookup service mock to raise a RuntimeError.

    Also rebuilds the AsyncClient with ``raise_app_exceptions=False`` so that
    Starlette's ``ServerErrorMiddleware`` returns the 500 response body instead
    of propagating the exception through the ASGI transport.

    Args:
        ctx: Shared mutable step context.
    """
    ctx["lookup_service"].handle_lookup = AsyncMock(
        side_effect=RuntimeError("Decision Store unreachable")
    )
    ctx["client"] = run_async(_make_client(ctx["app"], raise_app_exceptions=False))


# ---------------------------------------------------------------------------
# Given — bulk lookup (refresh-bulk)
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        'source "{source_id}" has {count:d} changed assignments to return with has_more {has_more}'
    )
)
def source_has_n_changed_assignments(ctx, source_id, count, has_more):
    """Configure the refresh-bulk service mock to return count deltas with the given has_more flag.

    When ``has_more`` is ``true``, a non-null ``continuation_cursor`` is also
    included in the response to satisfy the model invariant.

    Args:
        ctx: Shared mutable step context.
        source_id: Source system identifier.
        count: Number of delta LookupResponse items to return.
        has_more: String "true" or "false" indicating whether more pages exist.
    """
    ctx["bulk_source_id"] = source_id
    more = has_more.lower() == "true"
    deltas = [
        _make_lookup_response(
            source_id=source_id,
            request_id=f"req-{i:03d}",
            entity_type="ORGANISATION",
            cluster_id=f"cluster-{i:03d}",
            last_updated=datetime(2026, 3, 15, 10, i % 60, 0, tzinfo=UTC),
        )
        for i in range(count)
    ]
    ctx["refresh_bulk_service"].handle_refresh_bulk = AsyncMock(
        return_value=RefreshBulkResponse(
            deltas=deltas,
            has_more=more,
            continuation_cursor="cursor-next" if more else None,
        )
    )


@given(
    parsers.parse(
        'source "{source_id}" has {changed_count:d} changed assignments spread '
        "across 3 pages with page size {page_size:d}"
    )
)
def source_has_paginated_assignments(ctx, source_id, changed_count, page_size):
    """Configure the refresh-bulk mock with 3 pages of paginated results.

    Uses side_effect with a list so consecutive calls return successive pages.

    Args:
        ctx: Shared mutable step context.
        source_id: Source system identifier.
        changed_count: Total number of changed assignments (7 for the scenario).
        page_size: Number of deltas per page (3 for the scenario).
    """
    ctx["bulk_source_id"] = source_id

    def _make_deltas(start: int, count: int) -> list[LookupResponse]:
        return [
            _make_lookup_response(
                source_id=source_id,
                request_id=f"req-{start + i:03d}",
                entity_type="ORGANISATION",
                cluster_id=f"cluster-{start + i:03d}",
                last_updated=datetime(2026, 3, 15, 10, (start + i) % 60, 0, tzinfo=UTC),
            )
            for i in range(count)
        ]

    page1 = RefreshBulkResponse(
        deltas=_make_deltas(0, page_size),
        has_more=True,
        continuation_cursor="cursor-page-2",
    )
    page2 = RefreshBulkResponse(
        deltas=_make_deltas(page_size, page_size),
        has_more=True,
        continuation_cursor="cursor-page-3",
    )
    remaining = changed_count - 2 * page_size
    page3 = RefreshBulkResponse(
        deltas=_make_deltas(2 * page_size, remaining),
        has_more=False,
        continuation_cursor=None,
    )

    ctx["refresh_bulk_service"].handle_refresh_bulk = AsyncMock(
        side_effect=[page1, page2, page3]
    )


@given("the refresh-bulk service raises a runtime error")
def refresh_bulk_service_raises_error(ctx):
    """Configure the refresh-bulk service mock to raise a RuntimeError.

    Also rebuilds the AsyncClient with ``raise_app_exceptions=False`` so that
    Starlette's ``ServerErrorMiddleware`` returns the 500 response body instead
    of propagating the exception through the ASGI transport.

    Args:
        ctx: Shared mutable step context.
    """
    ctx["refresh_bulk_service"].handle_refresh_bulk = AsyncMock(
        side_effect=RuntimeError("Decision Store unreachable")
    )
    ctx["client"] = run_async(_make_client(ctx["app"], raise_app_exceptions=False))


@given(parsers.parse("a refresh-bulk request with {field_condition}"))
def refreshbulk_with_field_condition(ctx, field_condition):
    """Build a refresh-bulk request body with the specified invalid field.

    Args:
        ctx: Shared mutable step context.
        field_condition: Description of which field is invalid/absent/empty.
    """
    base: dict = {"source_id": "SYSTEM_X", "limit": 100}
    if "source_id absent" in field_condition:
        base.pop("source_id", None)
    elif "source_id set to empty" in field_condition:
        base["source_id"] = ""
    elif "limit set to zero" in field_condition:
        base["limit"] = 0
    elif "limit set to negative" in field_condition:
        base["limit"] = -1
    ctx["refreshbulk_request"] = base


# ---------------------------------------------------------------------------
# When — single-mention lookup
# ---------------------------------------------------------------------------


@when(
    parsers.parse(
        'I GET /api/v1/lookup with source_id "{source_id}", '
        'request_id "{request_id}", entity_type "{entity_type}"'
    )
)
def get_lookup(ctx, source_id, request_id, entity_type):
    """Issue GET /api/v1/lookup with the given query parameters.

    Args:
        ctx: Shared mutable step context.
        source_id: Query parameter value for source_id.
        request_id: Query parameter value for request_id.
        entity_type: Query parameter value for entity_type.
    """
    ctx["response"] = run_async(
        ctx["client"].get(
            "/api/v1/lookup",
            params={
                "source_id": source_id,
                "request_id": request_id,
                "entity_type": entity_type,
            },
        )
    )


@when("the lookup request is submitted")
def submit_lookup_request(ctx):
    """Issue GET /api/v1/lookup using the query params stored in ctx.

    Used by the validation-error outline scenario.

    Args:
        ctx: Shared mutable step context containing ``query_params``.
    """
    ctx["response"] = run_async(
        ctx["client"].get("/api/v1/lookup", params=ctx.get("query_params", {}))
    )


# ---------------------------------------------------------------------------
# When — bulk lookup (refresh-bulk)
# ---------------------------------------------------------------------------


@when(
    parsers.parse(
        'I POST to /api/v1/refresh-bulk for source "{source_id}" with limit {limit:d}'
    )
)
def post_refreshbulk_with_limit(ctx, source_id, limit):
    """Issue POST /api/v1/refresh-bulk with source_id and limit.

    Args:
        ctx: Shared mutable step context.
        source_id: Request body field.
        limit: Request body field.
    """
    ctx["response"] = run_async(
        ctx["client"].post(
            "/api/v1/refresh-bulk",
            json={"source_id": source_id, "limit": limit},
        )
    )


@when(
    parsers.parse(
        'I POST to /api/v1/refresh-bulk for source "{source_id}" with no continuation cursor'
    )
)
def post_refreshbulk_no_cursor(ctx, source_id):
    """Issue POST /api/v1/refresh-bulk without a continuation cursor.

    Args:
        ctx: Shared mutable step context.
        source_id: Request body field.
    """
    ctx["response"] = run_async(
        ctx["client"].post(
            "/api/v1/refresh-bulk",
            json={"source_id": source_id},
        )
    )


@when(
    parsers.parse(
        'I POST to /api/v1/refresh-bulk for source "{source_id}" '
        "using the returned continuation cursor with limit {limit:d}"
    )
)
def post_refreshbulk_with_cursor(ctx, source_id, limit):
    """Issue POST /api/v1/refresh-bulk using the cursor from the previous response.

    Args:
        ctx: Shared mutable step context.
        source_id: Request body field.
        limit: Request body field.
    """
    cursor = ctx["response"].json().get("continuation_cursor")
    ctx["response"] = run_async(
        ctx["client"].post(
            "/api/v1/refresh-bulk",
            json={
                "source_id": source_id,
                "limit": limit,
                "continuation_cursor": cursor,
            },
        )
    )


@when(
    parsers.parse(
        'I POST to /api/v1/refresh-bulk for source "{source_id}" without specifying a limit'
    )
)
def post_refreshbulk_no_limit(ctx, source_id):
    """Issue POST /api/v1/refresh-bulk omitting the limit field.

    Args:
        ctx: Shared mutable step context.
        source_id: Request body field.
    """
    ctx["response"] = run_async(
        ctx["client"].post(
            "/api/v1/refresh-bulk",
            json={"source_id": source_id},
        )
    )


@when("I POST to /api/v1/refresh-bulk")
def post_refreshbulk_raw(ctx):
    """Issue POST /api/v1/refresh-bulk using the request body stored in ctx.

    Used by the validation-error outline scenario.

    Args:
        ctx: Shared mutable step context containing ``refreshbulk_request``.
    """
    ctx["response"] = run_async(
        ctx["client"].post(
            "/api/v1/refresh-bulk",
            json=ctx.get("refreshbulk_request", {}),
        )
    )


@when(parsers.parse('I POST to /api/v1/refresh-bulk for source "{source_id}"'))
def post_refreshbulk_for_source(ctx, source_id):
    """Issue POST /api/v1/refresh-bulk with only source_id (no limit or cursor).

    Args:
        ctx: Shared mutable step context.
        source_id: Request body field.
    """
    ctx["response"] = run_async(
        ctx["client"].post(
            "/api/v1/refresh-bulk",
            json={"source_id": source_id},
        )
    )


# ---------------------------------------------------------------------------
# Then — single-mention lookup assertions
# ---------------------------------------------------------------------------


@then(parsers.parse('the response body cluster_reference contains "{cluster_id}"'))
def response_cluster_reference(ctx, cluster_id):
    """Assert the response body cluster_reference.cluster_id matches the expected value.

    Args:
        ctx: Shared mutable step context containing ``response``.
        cluster_id: Expected cluster identifier.
    """
    data = ctx["response"].json()
    assert data["cluster_reference"]["cluster_id"] == cluster_id


@then(parsers.parse('the response body last_updated is "{last_updated}"'))
def response_last_updated(ctx, last_updated):
    """Assert the response body last_updated parses to the expected timestamp.

    Comparison is done by normalising both to UTC ISO 8601 format.

    Args:
        ctx: Shared mutable step context containing ``response``.
        last_updated: Expected ISO 8601 timestamp string.
    """
    data = ctx["response"].json()
    actual = datetime.fromisoformat(data["last_updated"])
    expected = datetime.fromisoformat(last_updated)
    assert actual == expected


# ---------------------------------------------------------------------------
# Then — bulk lookup assertions
# ---------------------------------------------------------------------------


@then(parsers.parse("the response body contains {count:d} delta assignments"))
def response_contains_n_deltas(ctx, count):
    """Assert the response deltas list has exactly count items.

    Args:
        ctx: Shared mutable step context containing ``response``.
        count: Expected number of delta assignments.
    """
    data = ctx["response"].json()
    assert len(data["deltas"]) == count


@then(parsers.parse("the response body contains {count:d} delta assignment"))
def response_contains_one_delta(ctx, count):
    """Singular form of the delta count assertion (used for last pagination page).

    Args:
        ctx: Shared mutable step context containing ``response``.
        count: Expected number of delta assignments.
    """
    data = ctx["response"].json()
    assert len(data["deltas"]) == count


@then("each delta has identified_by, cluster_reference, and last_updated fields")
def each_delta_has_required_fields(ctx):
    """Assert every delta item contains the required fields.

    Args:
        ctx: Shared mutable step context containing ``response``.
    """
    data = ctx["response"].json()
    required = {"identified_by", "cluster_reference", "last_updated"}
    for delta in data["deltas"]:
        assert required.issubset(delta.keys()), (
            f"Delta missing required fields. Present: {set(delta.keys())}"
        )


@then(parsers.parse("the response body has_more is {has_more}"))
def response_has_more(ctx, has_more):
    """Assert the response body has_more field matches the expected boolean.

    Args:
        ctx: Shared mutable step context containing ``response``.
        has_more: Expected value as a string ("true" or "false").
    """
    data = ctx["response"].json()
    expected = has_more.lower() == "true"
    assert data["has_more"] is expected


@then("the continuation cursor is present")
def continuation_cursor_present(ctx):
    """Assert the response body includes a non-None continuation_cursor.

    Args:
        ctx: Shared mutable step context containing ``response``.
    """
    data = ctx["response"].json()
    assert data.get("continuation_cursor") is not None


@then("the continuation cursor is absent")
def continuation_cursor_absent(ctx):
    """Assert the response body has a null continuation_cursor.

    Args:
        ctx: Shared mutable step context containing ``response``.
    """
    data = ctx["response"].json()
    assert data.get("continuation_cursor") is None


@then(parsers.parse("the response body contains at most {max_count:d} delta assignments"))
def response_contains_at_most_n_deltas(ctx, max_count):
    """Assert the response deltas list has no more than max_count items.

    Args:
        ctx: Shared mutable step context containing ``response``.
        max_count: Maximum allowed number of delta assignments.
    """
    data = ctx["response"].json()
    assert len(data["deltas"]) <= max_count


# ---------------------------------------------------------------------------
# Then — read-only contract assertions
# ---------------------------------------------------------------------------


@then("no resolution service method was invoked")
def no_resolution_service_invoked(ctx):
    """Assert that no method on the resolve_service mock was called.

    This verifies the read-only contract: lookup and refresh-bulk operations
    must not trigger any resolution activity.

    Args:
        ctx: Shared mutable step context containing ``resolve_service``.
    """
    ctx["resolve_service"].handle_resolve.assert_not_called()
