"""
Step definitions for: resolve_entity_mention.feature

Feature: Resolve Entity Mention via REST API (Spine A)
  Covers single and bulk POST /resolve endpoint behaviour.

  These steps invoke the FastAPI entrypoint via an httpx.AsyncClient
  with the ResolveService mocked at the service boundary.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, create_autospec

import pytest
from erspec.models.core import EntityMentionIdentifier
from fastapi import FastAPI
from pytest_bdd import given, parsers, scenario, then, when
from starlette.testclient import TestClient

from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.ers_rest_api.domain.errors import ErrorCode, ErrorResponse
from ers.ers_rest_api.domain.resolution import (
    BulkResolveResponse,
    EntityMentionResolutionResult,
)
from ers.ers_rest_api.entrypoints.api.app import create_app
from ers.ers_rest_api.entrypoints.api.dependencies import (
    get_lookup_service,
    get_refresh_bulk_service,
    get_resolve_service,
)
from ers.ers_rest_api.services.lookup_service import LookupService
from ers.ers_rest_api.services.refresh_bulk_service import RefreshBulkService
from ers.ers_rest_api.services.resolve_service import ResolveService
from ers.request_registry.services.exceptions import IdempotencyConflictError
from ers.resolution_coordinator.domain.exceptions import ParsingFailedError

# ---------------------------------------------------------------------------
# NOTE: We use starlette.testclient.TestClient (sync) rather than
# httpx.AsyncClient so that the Starlette ServerErrorMiddleware can return
# 500 responses for unhandled exceptions instead of re-raising them to the
# caller.  The BDD step functions must be sync def (pytest-bdd requirement),
# making the sync client the natural fit here.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Feature file path
# ---------------------------------------------------------------------------

FEATURE_FILE = str(
    Path(__file__).parent.parent.parent
    / "feature"
    / "ers_rest_api"
    / "resolve_entity_mention.feature"
)


# ---------------------------------------------------------------------------
# Scenario bindings — single resolve
# ---------------------------------------------------------------------------


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
# Helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def _build_app(resolve_svc: AsyncMock, monkeypatch) -> FastAPI:
    monkeypatch.setenv("ERS_API_NAME", "Test ERS API")
    monkeypatch.setenv("DEBUG", "false")
    lookup_svc = create_autospec(LookupService, instance=True)
    refresh_svc = create_autospec(RefreshBulkService, instance=True)
    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    app.dependency_overrides[get_resolve_service] = lambda: resolve_svc
    app.dependency_overrides[get_lookup_service] = lambda: lookup_svc
    app.dependency_overrides[get_refresh_bulk_service] = lambda: refresh_svc
    return app


def _make_client(app: FastAPI) -> TestClient:
    """Return a sync TestClient that suppresses server-side exceptions.

    raise_server_exceptions=False lets the app's own @exception_handler(Exception)
    return a 500 response rather than re-raising through the ASGI transport.
    """
    return TestClient(app, raise_server_exceptions=False)


def _make_success_result(
    source_id: str,
    request_id: str,
    entity_type: str,
    cluster_id: str,
    outcome: ResolutionOutcome,
) -> EntityMentionResolutionResult:
    return EntityMentionResolutionResult(
        identified_by=EntityMentionIdentifier(
            source_id=source_id,
            request_id=request_id,
            entity_type=entity_type,
        ),
        canonical_entity_id=cluster_id,
        status=outcome,
    )


def _make_error_result(
    source_id: str,
    request_id: str,
    entity_type: str,
    error_code: ErrorCode,
    detail: str,
) -> EntityMentionResolutionResult:
    return EntityMentionResolutionResult(
        identified_by=EntityMentionIdentifier(
            source_id=source_id,
            request_id=request_id,
            entity_type=entity_type,
        ),
        error=ErrorResponse(error_code=error_code, message=detail),
    )


def _mention_payload(
    source_id: str,
    request_id: str,
    entity_type: str,
    content: str,
) -> dict:
    return {
        "mention": {
            "identifiedBy": {
                "source_id": source_id,
                "request_id": request_id,
                "entity_type": entity_type,
            },
            "content": content,
            "content_type": "application/ld+json",
        }
    }


def _run_post(app: FastAPI, path: str, *, json: dict | None = None, raw: bytes | None = None) -> object:
    client = _make_client(app)
    if raw is not None:
        return client.post(path, content=raw, headers={"Content-Type": "application/json"})
    return client.post(path, json=json)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Shared mutable context for passing state between step functions."""
    return {}


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("the ERS REST API is running")
def api_running(ctx, monkeypatch):
    svc = create_autospec(ResolveService, instance=True)
    ctx["resolve_service"] = svc
    ctx["app"] = _build_app(svc, monkeypatch)


@given("the Resolution Coordinator is available")
def coordinator_available(ctx):
    """Default state — service raises no exceptions. Configured per scenario."""


# ---------------------------------------------------------------------------
# Given — single resolve
# ---------------------------------------------------------------------------


@given(
    parsers.parse(
        'an entity mention with triad "{source_id}", "{request_id}", "{entity_type}"'
    )
)
def entity_mention_with_triad(ctx, source_id, request_id, entity_type):
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = entity_type


@given(parsers.parse('the mention content is "{content_fixture}"'))
def mention_content(ctx, content_fixture):
    ctx["content_fixture"] = content_fixture


@given(parsers.parse('the mention context is "{context}"'))
def mention_context(ctx, context):
    ctx["context"] = context if context else None


@given('the mention context is ""')
def mention_context_empty(ctx):
    ctx["context"] = None


@given(
    parsers.parse(
        'the Resolution Coordinator returns canonical identifier "{canonical_id}"'
    )
)
def coordinator_returns_canonical(ctx, canonical_id):
    ctx["resolve_service"].handle_resolve.return_value = _make_success_result(
        source_id=ctx["source_id"],
        request_id=ctx["request_id"],
        entity_type=ctx["entity_type"],
        cluster_id=canonical_id,
        outcome=ResolutionOutcome.CANONICAL,
    )


@given(
    parsers.parse(
        "the Resolution Coordinator returns provisional identifier "
        '"{provisional_id}" due to "{reason}"'
    )
)
def coordinator_returns_provisional(ctx, provisional_id, reason):
    ctx["resolve_service"].handle_resolve.return_value = _make_success_result(
        source_id=ctx["source_id"],
        request_id=ctx["request_id"],
        entity_type=ctx["entity_type"],
        cluster_id=provisional_id,
        outcome=ResolutionOutcome.PROVISIONAL,
    )


@given("the Resolution Coordinator raises a parsing error for unsupported entity type")
def coordinator_raises_parsing_error(ctx):
    ctx["resolve_service"].handle_resolve.side_effect = ParsingFailedError(
        message=f"Unsupported entity type: {ctx['entity_type']}",
        cause=ValueError(f"Unsupported entity type: {ctx['entity_type']}"),
    )


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
    ctx["source_id"] = source_id
    ctx["request_id"] = request_id
    ctx["entity_type"] = entity_type


@given(
    parsers.re(
        r'the original content was "(?P<content_fixture>[^"]+)" with context "(?P<context>[^"]*)"'
    )
)
def original_content_with_context(ctx, content_fixture, context):
    ctx["original_content"] = content_fixture
    ctx["original_context"] = context if context else None


@given(
    parsers.parse(
        'the original resolution returned "{cluster_id}" with status '
        '"{original_status}" and HTTP {original_http:d}'
    )
)
def original_resolution(ctx, cluster_id, original_status, original_http):
    ctx["original_cluster_id"] = cluster_id
    ctx["original_status"] = original_status
    ctx["original_http"] = original_http
    outcome = (
        ResolutionOutcome.CANONICAL
        if original_status == "CANONICAL"
        else ResolutionOutcome.PROVISIONAL
    )
    ctx["resolve_service"].handle_resolve.return_value = _make_success_result(
        source_id=ctx["source_id"],
        request_id=ctx["request_id"],
        entity_type=ctx["entity_type"],
        cluster_id=cluster_id,
        outcome=outcome,
    )


# ---------------------------------------------------------------------------
# Given — validation errors
# ---------------------------------------------------------------------------


@given(parsers.parse("an entity mention request with {missing_field} absent"))
def mention_with_missing_field(ctx, missing_field):
    identified_by: dict = {
        "source_id": "SYSTEM_X",
        "request_id": "req-val-001",
        "entity_type": "ORGANISATION",
    }
    if missing_field == "content":
        ctx["request_body"] = {
            "mention": {
                "identifiedBy": identified_by,
                "content_type": "application/ld+json",
            }
        }
    else:
        identified_by.pop(missing_field, None)
        ctx["request_body"] = {
            "mention": {
                "identifiedBy": identified_by,
                "content": '{"name": "Validation Test"}',
                "content_type": "application/ld+json",
            }
        }
    ctx["missing_field"] = missing_field


@given("a POST /resolve request with a syntactically invalid JSON body")
def malformed_json_body(ctx):
    ctx["raw_body"] = b"{not-valid-json"


@given("the Resolution Coordinator is unavailable")
def coordinator_unavailable(ctx):
    ctx["resolve_service"].handle_resolve.side_effect = RuntimeError(
        "Resolution Coordinator unreachable"
    )
    ctx["resolve_service"].handle_bulk_resolve.side_effect = RuntimeError(
        "Resolution Coordinator unreachable"
    )


# ---------------------------------------------------------------------------
# Given — bulk resolve
# ---------------------------------------------------------------------------


def _build_bulk_meta_and_request(entity_type: str, datatable: list) -> tuple[list, dict]:
    headers = datatable[0]
    meta = []
    mentions = []
    for row_values in datatable[1:]:
        row = dict(zip(headers, row_values, strict=True))
        content = row.get("content_fixture", "") or ""
        meta.append(
            {
                "source_id": row["source_id"],
                "request_id": row["request_id"],
                "entity_type": entity_type,
                "has_content": bool(content),
            }
        )
        mentions.append(
            _mention_payload(
                source_id=row["source_id"],
                request_id=row["request_id"],
                entity_type=entity_type,
                content=content if content else '{"name": "placeholder"}',
            )
        )
    return meta, {"mentions": mentions}


@given(
    parsers.parse(
        'a batch of {count:d} entity mentions for entity_type "{entity_type}":'
    )
)
def batch_with_count_and_datatable(ctx, count, entity_type, datatable):
    meta, bulk_request = _build_bulk_meta_and_request(entity_type, datatable)
    ctx["bulk_mentions_meta"] = meta
    ctx["bulk_request"] = bulk_request


@given(
    parsers.parse('a batch of entity mentions for entity_type "{entity_type}":')
)
def batch_without_count(ctx, entity_type, datatable):
    meta, bulk_request = _build_bulk_meta_and_request(entity_type, datatable)
    ctx["bulk_mentions_meta"] = meta
    ctx["bulk_request"] = bulk_request


@given("an empty batch of entity mentions")
def empty_batch(ctx):
    ctx["bulk_request"] = {"mentions": []}


@given("a bulk resolve request with all mentions missing required fields")
def bulk_all_missing_fields(ctx):
    """Bulk request where every mention omits content — Pydantic rejects at request level."""
    ctx["bulk_request"] = {
        "mentions": [
            {
                "mention": {
                    "identifiedBy": {
                        "source_id": "SYSTEM_D",
                        "request_id": "req-500",
                        "entity_type": "ORGANISATION",
                    }
                    # content omitted intentionally
                }
            }
        ]
    }


@given(parsers.parse('the Resolution Coordinator returns "{outcome}" for all mentions'))
def coordinator_returns_uniform_outcome(ctx, outcome):
    meta = ctx.get("bulk_mentions_meta", [])
    mapped_outcome = (
        ResolutionOutcome.CANONICAL if outcome == "canonical" else ResolutionOutcome.PROVISIONAL
    )
    results = [
        _make_success_result(
            source_id=m["source_id"],
            request_id=m["request_id"],
            entity_type=m["entity_type"],
            cluster_id=f"cluster-uniform-{i:03d}",
            outcome=mapped_outcome,
        )
        for i, m in enumerate(meta)
    ]
    ctx["resolve_service"].handle_bulk_resolve.return_value = BulkResolveResponse(
        results=results
    )


@given("the Resolution Coordinator returns per-mention outcomes:")
def coordinator_returns_per_mention_outcomes(ctx, datatable):
    headers = datatable[0]
    outcome_map = {}
    for row_values in datatable[1:]:
        row = dict(zip(headers, row_values, strict=True))
        outcome_map[row["request_id"]] = {
            "outcome": row["outcome"],
            "cluster_id": row["cluster_id"],
        }
    meta = ctx.get("bulk_mentions_meta", [])
    results = []
    for m in meta:
        info = outcome_map[m["request_id"]]
        mapped_outcome = (
            ResolutionOutcome.CANONICAL
            if info["outcome"] == "canonical"
            else ResolutionOutcome.PROVISIONAL
        )
        results.append(
            _make_success_result(
                source_id=m["source_id"],
                request_id=m["request_id"],
                entity_type=m["entity_type"],
                cluster_id=info["cluster_id"],
                outcome=mapped_outcome,
            )
        )
    ctx["resolve_service"].handle_bulk_resolve.return_value = BulkResolveResponse(
        results=results
    )


@given(
    parsers.parse(
        'the Resolution Coordinator returns canonical identifier "{cluster_id}" for valid mentions'
    )
)
def coordinator_returns_canonical_for_valid(ctx, cluster_id):
    """Return canonical for valid mentions; error for conflicting/missing content items.

    - If a prior triad is in ctx (idempotency conflict scenario), that item
      gets an IDEMPOTENCY_CONFLICT error result.
    - If a mention has no real content (placeholder), it gets a VALIDATION_ERROR.
    - All others get a canonical result.
    """
    meta = ctx.get("bulk_mentions_meta", [])
    prior_request_id = ctx.get("request_id")  # set by mention_previously_resolved
    results = []
    for m in meta:
        is_conflict = prior_request_id and m["request_id"] == prior_request_id
        has_no_content = not m.get("has_content", True)

        if is_conflict:
            identifier = EntityMentionIdentifier(
                source_id=m["source_id"],
                request_id=m["request_id"],
                entity_type=m["entity_type"],
            )
            results.append(
                _make_error_result(
                    source_id=m["source_id"],
                    request_id=m["request_id"],
                    entity_type=m["entity_type"],
                    error_code=ErrorCode.IDEMPOTENCY_CONFLICT,
                    detail=str(IdempotencyConflictError(identifier)),
                )
            )
        elif has_no_content:
            results.append(
                _make_error_result(
                    source_id=m["source_id"],
                    request_id=m["request_id"],
                    entity_type=m["entity_type"],
                    error_code=ErrorCode.VALIDATION_ERROR,
                    detail="content is required",
                )
            )
        else:
            results.append(
                _make_success_result(
                    source_id=m["source_id"],
                    request_id=m["request_id"],
                    entity_type=m["entity_type"],
                    cluster_id=cluster_id,
                    outcome=ResolutionOutcome.CANONICAL,
                )
            )
    ctx["resolve_service"].handle_bulk_resolve.return_value = BulkResolveResponse(
        results=results
    )


@given(
    parsers.parse(
        'the Resolution Coordinator returns canonical identifier "{cluster_id}" for new mentions'
    )
)
def coordinator_returns_canonical_for_new(ctx, cluster_id):
    """Return the prior result for the replay triad; new canonical for all others."""
    meta = ctx.get("bulk_mentions_meta", [])
    prior_request_id = ctx.get("request_id")
    prior_cluster_id = ctx.get("original_cluster_id")
    results = []
    for m in meta:
        if m["request_id"] == prior_request_id and prior_cluster_id:
            results.append(
                _make_success_result(
                    source_id=m["source_id"],
                    request_id=m["request_id"],
                    entity_type=m["entity_type"],
                    cluster_id=prior_cluster_id,
                    outcome=ResolutionOutcome.CANONICAL,
                )
            )
        else:
            results.append(
                _make_success_result(
                    source_id=m["source_id"],
                    request_id=m["request_id"],
                    entity_type=m["entity_type"],
                    cluster_id=cluster_id,
                    outcome=ResolutionOutcome.CANONICAL,
                )
            )
    ctx["resolve_service"].handle_bulk_resolve.return_value = BulkResolveResponse(
        results=results
    )


# ---------------------------------------------------------------------------
# When — single resolve
# ---------------------------------------------------------------------------


@when("I POST to /resolve")
def post_resolve(ctx):
    if ctx.get("raw_body") is not None:
        ctx["response"] = _run_post(ctx["app"], "/api/v1/resolve", raw=ctx["raw_body"])
    elif "request_body" in ctx:
        ctx["response"] = _run_post(ctx["app"], "/api/v1/resolve", json=ctx["request_body"])
    else:
        payload = _mention_payload(
            source_id=ctx["source_id"],
            request_id=ctx["request_id"],
            entity_type=ctx["entity_type"],
            content=ctx.get("content_fixture", '{"name": "default"}'),
        )
        ctx["response"] = _run_post(ctx["app"], "/api/v1/resolve", json=payload)


@when("I POST to /resolve with identical triad, content, and context")
def post_resolve_replay(ctx):
    payload = _mention_payload(
        source_id=ctx["source_id"],
        request_id=ctx["request_id"],
        entity_type=ctx["entity_type"],
        content=ctx["original_content"],
    )
    ctx["response"] = _run_post(ctx["app"], "/api/v1/resolve", json=payload)


@when(
    parsers.parse(
        "I POST to /resolve with the same triad but content "
        '"{new_fixture}" and context "{new_context}"'
    )
)
def post_resolve_conflict(ctx, new_fixture, new_context):
    identifier = EntityMentionIdentifier(
        source_id=ctx["source_id"],
        request_id=ctx["request_id"],
        entity_type=ctx["entity_type"],
    )
    ctx["resolve_service"].handle_resolve.side_effect = IdempotencyConflictError(
        identifier
    )
    payload = _mention_payload(
        source_id=ctx["source_id"],
        request_id=ctx["request_id"],
        entity_type=ctx["entity_type"],
        content=new_fixture,
    )
    ctx["response"] = _run_post(ctx["app"], "/api/v1/resolve", json=payload)


@when("the request is submitted")
def submit_raw_request(ctx):
    if ctx.get("raw_body") is not None:
        ctx["response"] = _run_post(ctx["app"], "/api/v1/resolve", raw=ctx["raw_body"])
    else:
        ctx["response"] = _run_post(
            ctx["app"], "/api/v1/resolve", json=ctx.get("request_body", {})
        )


# ---------------------------------------------------------------------------
# When — bulk resolve
# ---------------------------------------------------------------------------


@when("I POST to /resolve-bulk")
def post_resolve_bulk(ctx):
    ctx["response"] = _run_post(ctx["app"], "/api/v1/resolve-bulk", json=ctx["bulk_request"])


# ---------------------------------------------------------------------------
# Then — shared assertions
# ---------------------------------------------------------------------------


@then(parsers.parse("the response HTTP status is {status_code:d}"))
def assert_http_status(ctx, status_code):
    assert ctx["response"].status_code == status_code, (
        f"Expected HTTP {status_code}, got {ctx['response'].status_code}. "
        f"Body: {ctx['response'].text}"
    )


@then(parsers.parse('the response body canonical_entity_id is "{cluster_id}"'))
def response_canonical_entity_id(ctx, cluster_id):
    data = ctx["response"].json()
    assert data["canonical_entity_id"] == cluster_id, (
        f"Expected canonical_entity_id={cluster_id!r}, got {data.get('canonical_entity_id')!r}"
    )


@then(parsers.parse('the response body status is "{expected_status}"'))
def response_status(ctx, expected_status):
    data = ctx["response"].json()
    assert data["status"] == expected_status, (
        f"Expected status={expected_status!r}, got {data.get('status')!r}"
    )


@then(parsers.parse('the response body identified_by request_id is "{request_id}"'))
def response_identified_by_request_id(ctx, request_id):
    data = ctx["response"].json()
    actual = data.get("identified_by", {}).get("request_id")
    assert actual == request_id, (
        f"Expected identified_by.request_id={request_id!r}, got {actual!r}"
    )


@then(parsers.parse('the response body error code is "{error_code}"'))
def response_error_code(ctx, error_code):
    data = ctx["response"].json()
    assert data.get("error_code") == error_code, (
        f"Expected error_code={error_code!r}, got {data.get('error_code')!r}. Body: {data}"
    )


@then("the response body contains a human-readable error message")
def response_has_error_message(ctx):
    data = ctx["response"].json()
    assert data.get("message"), f"Expected a non-empty 'message' field. Body: {data}"


@then(parsers.parse('the response body error detail references "{field_name}"'))
def response_error_detail_references_field(ctx, field_name):
    data = ctx["response"].json()
    message = str(data.get("message", ""))
    assert field_name in message, (
        f"Expected '{field_name}' in error message, got: {message!r}"
    )


# ---------------------------------------------------------------------------
# Then — bulk resolve assertions
# ---------------------------------------------------------------------------


@then(parsers.parse("the response body contains {count:d} individual results"))
def response_contains_n_results(ctx, count):
    data = ctx["response"].json()
    results = data.get("results", [])
    assert len(results) == count, (
        f"Expected {count} results, got {len(results)}. Body: {data}"
    )


@then(parsers.parse('every individual result status is "{expected_status}"'))
def all_results_have_status(ctx, expected_status):
    data = ctx["response"].json()
    for result in data["results"]:
        assert result["status"] == expected_status, (
            f"Expected all statuses={expected_status!r}, found: {result}"
        )


@then(
    parsers.parse(
        'individual result for "{request_id}" has status "{status}" '
        'and canonical_entity_id "{cluster_id}"'
    )
)
def individual_result_status_and_id(ctx, request_id, status, cluster_id):
    data = ctx["response"].json()
    result = next(
        (r for r in data["results"] if r["identified_by"]["request_id"] == request_id),
        None,
    )
    assert result is not None, (
        f"No result for request_id={request_id!r}. "
        f"Available: {[r['identified_by']['request_id'] for r in data['results']]}"
    )
    assert result["status"] == status, (
        f"For {request_id}: expected status={status!r}, got {result.get('status')!r}"
    )
    assert result["canonical_entity_id"] == cluster_id, (
        f"For {request_id}: expected canonical_entity_id={cluster_id!r}, "
        f"got {result.get('canonical_entity_id')!r}"
    )


@then(parsers.parse('individual result for "{request_id}" has error code "{error_code}"'))
def individual_result_error(ctx, request_id, error_code):
    data = ctx["response"].json()
    result = next(
        (r for r in data["results"] if r["identified_by"]["request_id"] == request_id),
        None,
    )
    assert result is not None, f"No result for request_id={request_id!r}."
    assert result.get("error", {}).get("error_code") == error_code, (
        f"For {request_id}: expected error.error_code={error_code!r}, "
        f"got {result.get('error')!r}"
    )


@then(parsers.parse('individual result for "{request_id}" has status "{status}"'))
def individual_result_status_only(ctx, request_id, status):
    data = ctx["response"].json()
    result = next(
        (r for r in data["results"] if r["identified_by"]["request_id"] == request_id),
        None,
    )
    assert result is not None, f"No result for request_id={request_id!r}."
    assert result["status"] == status, (
        f"For {request_id}: expected status={status!r}, got {result.get('status')!r}"
    )
