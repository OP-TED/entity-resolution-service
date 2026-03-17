"""
Step definitions for: resolve_entity_mention.feature

Feature: Resolve Entity Mention via REST API (Spine A)
  Covers single and bulk POST /resolve endpoint behaviour:

  Single resolve (POST /resolve):
    1. Canonical resolution — ERE responds within execution window.
    2. Provisional resolution — ERE timeout or unreachable (202).
    3. Idempotent replay — identical triad + content + context.
    4. Idempotency conflict — same triad, different content or context → 400.
    5. Validation errors — missing required fields (Outline).
    6. Unsupported entity type → 400.
    7. Malformed JSON body → 400.
    8. Resolution Coordinator unavailable → 500.

  Bulk resolve (POST /resolveBulk):
    9.  Uniform outcomes — all canonical (200) or all provisional (202).
    10. Mixed canonical and provisional → 207.
    11. Partial validation failures → 207.
    12. All mentions fail validation → 400.
    13. Per-mention idempotent replay within a batch.
    14. Per-mention idempotency conflict within a batch → 207.
    15. Empty mention list → 400.
    16. Resolution Coordinator unavailable → 500.

  These steps invoke the FastAPI entrypoint via a TestClient
  with the ResolveService and ResolveBulkService mocked at the service boundary.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, parsers, scenario, then, when

# ---------------------------------------------------------------------------
# Scenario bindings — single resolve
# ---------------------------------------------------------------------------

FEATURE_FILE = str(
    Path(__file__).parent.parent.parent
    / "features"
    / "ers_rest_api"
    / "resolve_entity_mention.feature"
)


@scenario(
    FEATURE_FILE,
    "Canonical resolution when ERE responds within the execution window",
)
def test_canonical_resolution():
    pass


@scenario(
    FEATURE_FILE,
    "Provisional resolution when ERE does not respond in time or is unreachable",
)
def test_provisional_resolution():
    pass


@scenario(FEATURE_FILE, "Replay of an identical request returns the same identifier")
def test_idempotent_replay():
    pass


@scenario(
    FEATURE_FILE,
    "Reject request when triad reused with different content or context",
)
def test_idempotency_conflict():
    pass


@scenario(FEATURE_FILE, "Reject resolve request with missing required fields")
def test_missing_required_fields():
    pass


@scenario(FEATURE_FILE, "Reject resolve request with unsupported entity type")
def test_unsupported_entity_type():
    pass


@scenario(FEATURE_FILE, "Reject resolve request with malformed JSON body")
def test_malformed_body():
    pass


@scenario(
    FEATURE_FILE,
    "Return service error when the Resolution Coordinator is unavailable",
)
def test_coordinator_unavailable():
    pass


# ---------------------------------------------------------------------------
# Scenario bindings — bulk resolve
# ---------------------------------------------------------------------------


@scenario(FEATURE_FILE, "Bulk resolve with uniform outcomes")
def test_bulk_uniform_outcomes():
    pass


@scenario(FEATURE_FILE, "Bulk resolve with mixed canonical and provisional outcomes")
def test_bulk_mixed_outcomes():
    pass


@scenario(
    FEATURE_FILE,
    "Bulk resolve with partial validation failures returns mixed response",
)
def test_bulk_partial_validation_failures():
    pass


@scenario(FEATURE_FILE, "Bulk resolve rejected when all mentions fail validation")
def test_bulk_all_fail_validation():
    pass


@scenario(FEATURE_FILE, "Bulk resolve with an idempotent replay and a new mention")
def test_bulk_idempotent_replay():
    pass


@scenario(FEATURE_FILE, "Bulk resolve with an idempotency conflict within the batch")
def test_bulk_idempotency_conflict():
    pass


@scenario(FEATURE_FILE, "Reject bulk resolve with an empty mention list")
def test_bulk_empty_list():
    pass


@scenario(
    FEATURE_FILE,
    "Return service error for bulk resolve when the Resolution Coordinator is unavailable",
)
def test_bulk_coordinator_unavailable():
    pass


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Shared mutable context for passing state between step functions."""
    return {}


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("the ERS REST API is running")
def api_running(ctx):
    """
    Set up the FastAPI TestClient with all service dependencies mocked.

    TODO: Build a FastAPI TestClient wrapping the ERS app:
      from httpx import AsyncClient
      ctx["resolve_service"] = MagicMock()
      ctx["resolve_bulk_service"] = MagicMock()
      ctx["app"] = create_app(
          resolve_service=ctx["resolve_service"],
          resolve_bulk_service=ctx["resolve_bulk_service"],
      )
      ctx["client"] = AsyncClient(app=ctx["app"], base_url="http://test")
    """
    ctx["resolve_service"] = MagicMock()
    ctx["resolve_bulk_service"] = MagicMock()
    ctx["client"] = None  # TODO: build real AsyncClient


@given("the Resolution Coordinator is available")
def coordinator_available(ctx):
    """
    Ensure the mocked Resolution Coordinator is in a healthy state
    (default — does not raise exceptions).

    TODO: Configure ctx["resolve_service"] default to return a valid response.
    """
    pass


# ---------------------------------------------------------------------------
# Given — single resolve
# ---------------------------------------------------------------------------


@given(parsers.parse('an entity mention with triad "{source_id}", "{request_id}", "{entity_type}"'))
def entity_mention_with_triad(ctx, source_id, request_id, entity_type):
    """
    Build the base request body for POST /resolve with the correlation triad.

    TODO: ctx["request_body"] = {
        "source_id": source_id,
        "request_id": request_id,
        "entity_type": entity_type,
    }
    """
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = entity_type
    ctx["request_body"] = {
        "source_id": source_id,
        "request_id": request_id,
        "entity_type": entity_type,
    }


@given(parsers.parse('the mention content is "{content_fixture}"'))
def mention_content(ctx, content_fixture):
    """
    Set the content field on the request body from a mock fixture reference.

    TODO: Resolve content_fixture to actual RDF Turtle mock data:
      ctx["request_body"]["content"] = load_fixture(content_fixture)
    """
    ctx["content_fixture"] = content_fixture
    ctx.setdefault("request_body", {})["content"] = content_fixture


@given(parsers.parse('the mention context is "{context}"'))
def mention_context(ctx, context):
    """
    Set the optional context field (e.g. NoticeID) on the request body.
    Empty string maps to None (context is optional).

    TODO: ctx["request_body"]["context"] = context if context else None
    """
    ctx.setdefault("request_body", {})["context"] = context if context else None


@given(parsers.parse('the mention context is ""'))
def mention_context_empty(ctx):
    """Context is absent (empty in the Examples table)."""
    ctx.setdefault("request_body", {})["context"] = None


@given(parsers.parse('the Resolution Coordinator returns canonical identifier "{canonical_id}"'))
def coordinator_returns_canonical(ctx, canonical_id):
    """
    Configure the mocked resolve service to return a canonical result.

    TODO: ctx["resolve_service"].handle_resolve = AsyncMock(
        return_value=ResolveResponse(
            canonical_entity_id=canonical_id,
            status=ResolutionStatus.CANONICAL,
            request_id=ctx["request_id"],
        )
    )
    """
    ctx["expected_canonical_id"] = canonical_id
    ctx["coordinator_outcome"] = "canonical"


@given(
    parsers.parse(
        "the Resolution Coordinator returns provisional identifier "
        '"{provisional_id}" due to "{reason}"'
    )
)
def coordinator_returns_provisional(ctx, provisional_id, reason):
    """
    Configure the mocked resolve service to return a provisional result.
    Reason distinguishes ere_timeout from ere_unreachable at the coordinator level.

    TODO: ctx["resolve_service"].handle_resolve = AsyncMock(
        return_value=ResolveResponse(
            canonical_entity_id=provisional_id,
            status=ResolutionStatus.PROVISIONAL,
            request_id=ctx["request_id"],
        )
    )
    """
    ctx["expected_provisional_id"] = provisional_id
    ctx["provisional_reason"] = reason
    ctx["coordinator_outcome"] = "provisional"


# ---------------------------------------------------------------------------
# Given — idempotent replay
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        'a mention with triad "{source_id}", "{request_id}", '
        '"{entity_type}" was previously resolved'
    )
)
def mention_previously_resolved(ctx, source_id, request_id, entity_type):
    """
    Record a triad that was previously resolved. Used by replay and conflict
    scenarios. The prior resolution details are set by subsequent Given steps.

    TODO: Seed the mock resolve service with a prior result for this triad.
    """
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = entity_type
    ctx["prior_triad"] = (source_id, request_id, entity_type)


@given(parsers.re(r'the original content was "(?P<content_fixture>[^"]+)" with context "(?P<context>[^"]*)"'))
def original_content_with_context(ctx, content_fixture, context):
    """
    Record the original content and context for the previously resolved mention.

    TODO: Store original payload for replay comparison.
    """
    ctx["original_content"] = content_fixture
    ctx["original_context"] = context if context else None


@given(
    parsers.parse(
        'the original resolution returned "{cluster_id}" with status '
        '"{original_status}" and HTTP {original_http:d}'
    )
)
def original_resolution(ctx, cluster_id, original_status, original_http):
    """
    Configure the mock to return the same response on replay.

    TODO: ctx["resolve_service"].handle_resolve = AsyncMock(
        return_value=ResolveResponse(
            canonical_entity_id=cluster_id,
            status=ResolutionStatus[original_status],
            request_id=ctx["request_id"],
        )
    )
    """
    ctx["original_cluster_id"] = cluster_id
    ctx["original_status"] = original_status
    ctx["original_http"] = original_http


# ---------------------------------------------------------------------------
# Given — validation errors
# ---------------------------------------------------------------------------


@given(parsers.parse("an entity mention request with {missing_field} absent"))
def mention_with_missing_field(ctx, missing_field):
    """
    Build a request body omitting the specified required field.

    TODO: base = {
        "source_id": "SYSTEM_X", "request_id": "req-val-001",
        "entity_type": "ORGANISATION", "content": "mock:org-001",
    }
    base.pop(missing_field, None)
    ctx["request_body"] = base
    """
    base = {
        "source_id": "SYSTEM_X",
        "request_id": "req-val-001",
        "entity_type": "ORGANISATION",
        "content": "mock:org-001",
    }
    base.pop(missing_field, None)
    ctx["request_body"] = base


@given("a POST /resolve request with a syntactically invalid JSON body")
def malformed_json_body(ctx):
    """Store a raw invalid-JSON bytes payload for the when-step."""
    ctx["raw_body"] = b"{not-valid-json"


@given("the Resolution Coordinator is unavailable")
def coordinator_unavailable(ctx):
    """
    Configure the mocked resolve service to raise ServiceException.

    TODO: ctx["resolve_service"].handle_resolve = AsyncMock(
        side_effect=ServiceException("Resolution Coordinator unreachable")
    )
    """
    ctx["coordinator_unavailable"] = True


# ---------------------------------------------------------------------------
# Given — bulk resolve
# ---------------------------------------------------------------------------


@given(parsers.parse('a batch of {count:d} entity mentions for entity_type "{entity_type}":'))
def batch_with_count_and_datatable(ctx, count, entity_type, datatable):
    """
    Build the batch request body from the embedded data table.

    TODO: ctx["bulk_request"] = {
        "mentions": [
            {
                "source_id": row["source_id"],
                "request_id": row["request_id"],
                "entity_type": entity_type,
                "content": row["content_fixture"],
                "context": row["context"] or None,
            }
            for row in datatable
        ]
    }
    """
    ctx["batch_entity_type"] = entity_type
    ctx["batch_mentions"] = []
    headers = datatable[0]
    for row_values in datatable[1:]:
        row = dict(zip(headers, row_values))
        mention = {
            "source_id": row["source_id"],
            "request_id": row["request_id"],
            "entity_type": entity_type,
            "content": row["content_fixture"],
            "context": row["context"] if row["context"] else None,
        }
        ctx["batch_mentions"].append(mention)
    ctx["bulk_request"] = {"mentions": ctx["batch_mentions"]}


@given(parsers.parse('a batch of entity mentions for entity_type "{entity_type}":'))
def batch_without_count(ctx, entity_type, datatable):
    """
    Build the batch request body from the data table (count inferred).

    TODO: Same as batch_with_count_and_datatable but count derived from table rows.
    """
    ctx["batch_entity_type"] = entity_type
    ctx["batch_mentions"] = []
    headers = datatable[0]
    for row_values in datatable[1:]:
        row = dict(zip(headers, row_values))
        mention = {
            "source_id": row["source_id"],
            "request_id": row["request_id"],
            "entity_type": entity_type,
            "content": row["content_fixture"],
            "context": row["context"] if row["context"] else None,
        }
        ctx["batch_mentions"].append(mention)
    ctx["bulk_request"] = {"mentions": ctx["batch_mentions"]}


@given("an empty batch of entity mentions")
def empty_batch(ctx):
    """Build a bulk request with an empty mentions list."""
    ctx["bulk_request"] = {"mentions": []}


@given(parsers.parse('the Resolution Coordinator returns "{outcome}" for all mentions'))
def coordinator_returns_uniform_outcome(ctx, outcome):
    """
    Configure the mocked bulk resolve service to return the same outcome
    for every mention in the batch.

    TODO: Configure ctx["resolve_bulk_service"] to return per-item responses
          with uniform status (all CANONICAL or all PROVISIONAL).
    """
    ctx["bulk_outcome"] = outcome


@given("the Resolution Coordinator returns per-mention outcomes:")
def coordinator_returns_per_mention_outcomes(ctx, datatable):
    """
    Configure the mocked bulk resolve service to return different outcomes
    per mention, as specified in the data table.

    TODO: Build a mapping of request_id → (outcome, cluster_id) and configure
          ctx["resolve_bulk_service"] accordingly.
    """
    ctx["per_mention_outcomes"] = {}
    headers = datatable[0]
    for row_values in datatable[1:]:
        row = dict(zip(headers, row_values))
        ctx["per_mention_outcomes"][row["request_id"]] = {
            "outcome": row["outcome"],
            "cluster_id": row["cluster_id"],
        }


@given(
    parsers.parse(
        'the Resolution Coordinator returns canonical identifier "{cluster_id}" for valid mentions'
    )
)
def coordinator_returns_canonical_for_valid(ctx, cluster_id):
    """
    Configure the mock to return a canonical identifier for all valid
    (non-error) mentions in the batch.

    TODO: ctx["resolve_bulk_service"] returns cluster_id for valid items,
          raises per-item errors for invalid items.
    """
    ctx["bulk_canonical_id"] = cluster_id


@given(
    parsers.parse(
        'the Resolution Coordinator returns canonical identifier "{cluster_id}" for new mentions'
    )
)
def coordinator_returns_canonical_for_new(ctx, cluster_id):
    """
    Configure the mock to return a canonical identifier for new (non-replay)
    mentions in the batch.

    TODO: ctx["resolve_bulk_service"] returns cluster_id for new triads,
          returns the replayed result for existing triads.
    """
    ctx["bulk_new_canonical_id"] = cluster_id


# ---------------------------------------------------------------------------
# When — single resolve
# ---------------------------------------------------------------------------


@when("I POST to /resolve")
def post_resolve(ctx):
    """
    Submit the entity mention request to POST /resolve.

    TODO:
      if ctx.get("raw_body") is not None:
          ctx["response"] = await ctx["client"].post(
              "/resolve",
              content=ctx["raw_body"],
              headers={"Content-Type": "application/json"},
          )
      else:
          ctx["response"] = await ctx["client"].post(
              "/resolve", json=ctx["request_body"]
          )
    """
    ctx["response"] = None  # TODO: replace with real client call


@when("I POST to /resolve with identical triad, content, and context")
def post_resolve_replay(ctx):
    """
    Replay the same request with identical triad, content, and context.

    TODO: Rebuild ctx["request_body"] from ctx["prior_triad"],
          ctx["original_content"], ctx["original_context"], then POST.
    """
    ctx["response"] = None  # TODO: replace with real client call


@when(
    parsers.parse(
        "I POST to /resolve with the same triad but content "
        '"{new_fixture}" and context "{new_context}"'
    )
)
def post_resolve_conflict(ctx, new_fixture, new_context):
    """
    Submit a conflicting request with the same triad but different content/context.

    TODO: ctx["request_body"] = {
        "source_id": ctx["source_id"],
        "request_id": ctx["request_id"],
        "entity_type": ctx["entity_type"],
        "content": new_fixture,
        "context": new_context if new_context else None,
    }
    ctx["response"] = await ctx["client"].post("/resolve", json=ctx["request_body"])
    """
    ctx["response"] = None  # TODO: replace with real client call


@when("the request is submitted")
def submit_raw_request(ctx):
    """
    Generic step for malformed-body scenarios.

    TODO:
      if ctx.get("raw_body") is not None:
          ctx["response"] = await ctx["client"].post(
              "/resolve",
              content=ctx["raw_body"],
              headers={"Content-Type": "application/json"},
          )
      else:
          ctx["response"] = await ctx["client"].post(
              "/resolve", json=ctx.get("request_body", {})
          )
    """
    ctx["response"] = None  # TODO: replace with real client call


# ---------------------------------------------------------------------------
# When — bulk resolve
# ---------------------------------------------------------------------------


@when("I POST to /resolveBulk")
def post_resolve_bulk(ctx):
    """
    Submit the batch request to POST /resolveBulk.

    TODO: ctx["response"] = await ctx["client"].post(
        "/resolveBulk", json=ctx["bulk_request"]
    )
    """
    ctx["response"] = None  # TODO: replace with real client call


# ---------------------------------------------------------------------------
# Then — shared assertions
# ---------------------------------------------------------------------------


@then(parsers.parse("the response HTTP status is {status_code:d}"))
def assert_http_status(ctx, status_code):
    """
    TODO: assert ctx["response"].status_code == status_code
    """
    assert True  # TODO: implement


@then(parsers.parse('the response body canonical_entity_id is "{cluster_id}"'))
def response_canonical_entity_id(ctx, cluster_id):
    """
    TODO: data = ctx["response"].json()
          assert data["canonical_entity_id"] == cluster_id
    """
    assert True  # TODO: implement


@then(parsers.parse('the response body status is "{expected_status}"'))
def response_status(ctx, expected_status):
    """
    TODO: data = ctx["response"].json()
          assert data["status"] == expected_status
    """
    assert True  # TODO: implement


@then(parsers.parse('the response body request_id is "{request_id}"'))
def response_request_id(ctx, request_id):
    """
    TODO: data = ctx["response"].json()
          assert data["request_id"] == request_id
    """
    assert True  # TODO: implement


@then(parsers.parse('the response body error code is "{error_code}"'))
def response_error_code(ctx, error_code):
    """
    TODO: data = ctx["response"].json()
          assert data["error_code"] == error_code
    """
    assert True  # TODO: implement


@then("the response body contains a human-readable error message")
def response_has_error_message(ctx):
    """
    TODO: data = ctx["response"].json()
          assert data.get("message") or data.get("detail")
    """
    assert True  # TODO: implement


@then(parsers.parse('the response body error detail references "{field_name}"'))
def response_error_detail_references_field(ctx, field_name):
    """
    TODO: data = ctx["response"].json()
          error_detail = str(data.get("detail", ""))
          assert field_name in error_detail
    """
    assert True  # TODO: implement


# ---------------------------------------------------------------------------
# Then — bulk resolve assertions
# ---------------------------------------------------------------------------


@then(parsers.parse("the response body contains {count:d} individual results"))
def response_contains_n_results(ctx, count):
    """
    TODO: data = ctx["response"].json()
          assert len(data["results"]) == count
    """
    assert True  # TODO: implement


@then(parsers.parse('every individual result status is "{expected_status}"'))
def all_results_have_status(ctx, expected_status):
    """
    TODO: data = ctx["response"].json()
          for result in data["results"]:
              assert result["status"] == expected_status
    """
    assert True  # TODO: implement


@then(
    parsers.parse(
        'individual result for "{request_id}" has status "{status}" '
        'and canonical_entity_id "{cluster_id}"'
    )
)
def individual_result_status_and_id(ctx, request_id, status, cluster_id):
    """
    TODO: data = ctx["response"].json()
          result = next(r for r in data["results"] if r["request_id"] == request_id)
          assert result["status"] == status
          assert result["canonical_entity_id"] == cluster_id
    """
    assert True  # TODO: implement


@then(parsers.parse('individual result for "{request_id}" has error code "{error_code}"'))
def individual_result_error(ctx, request_id, error_code):
    """
    TODO: data = ctx["response"].json()
          result = next(r for r in data["results"] if r["request_id"] == request_id)
          assert result["error_code"] == error_code
    """
    assert True  # TODO: implement


@then(parsers.parse('individual result for "{request_id}" has status "{status}"'))
def individual_result_status_only(ctx, request_id, status):
    """
    TODO: data = ctx["response"].json()
          result = next(r for r in data["results"] if r["request_id"] == request_id)
          assert result["status"] == status
    """
    assert True  # TODO: implement


@then(parsers.parse("the response body contains {count:d} individual error details"))
def response_contains_n_error_details(ctx, count):
    """
    TODO: data = ctx["response"].json()
          assert len(data.get("details", [])) == count
    """
    assert True  # TODO: implement
