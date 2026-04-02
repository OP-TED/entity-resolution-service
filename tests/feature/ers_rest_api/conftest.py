"""Shared fixtures and step definitions for ERS REST API BDD feature tests.

Provides the shared ``ctx`` fixture, the FastAPI app/client wiring (Background
steps), and common assertion steps reused across all ers_rest_api feature test
files.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, create_autospec

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pytest_bdd import given, parsers, then

from ers.ers_rest_api.entrypoints.api.app import create_app
from ers.ers_rest_api.entrypoints.api.dependencies import (
    get_lookup_service,
    get_refresh_bulk_service,
    get_resolve_service,
)
from ers.ers_rest_api.services.lookup_service import LookupService
from ers.ers_rest_api.services.refresh_bulk_service import RefreshBulkService
from ers.ers_rest_api.services.resolve_service import ResolveService

# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------


def run_async(coro):
    """Run a coroutine synchronously inside a sync pytest-bdd step.

    Args:
        coro: The coroutine to execute.

    Returns:
        The return value of the coroutine.
    """
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Shared context fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Shared mutable context for passing state between step functions."""
    return {}


# ---------------------------------------------------------------------------
# App/client factory helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def _build_app(
    monkeypatch,
    resolve_service: AsyncMock,
    lookup_service: AsyncMock,
    refresh_bulk_service: AsyncMock,
) -> FastAPI:
    """Create the ERS FastAPI app with injected service mocks.

    Args:
        monkeypatch: pytest monkeypatch fixture for setting env vars.
        resolve_service: Mocked ResolveService.
        lookup_service: Mocked LookupService.
        refresh_bulk_service: Mocked RefreshBulkService.

    Returns:
        A configured FastAPI application ready for testing.
    """
    monkeypatch.setenv("ERS_API_NAME", "Test ERS API")
    monkeypatch.setenv("DEBUG", "false")
    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    app.dependency_overrides[get_resolve_service] = lambda: resolve_service
    app.dependency_overrides[get_lookup_service] = lambda: lookup_service
    app.dependency_overrides[get_refresh_bulk_service] = lambda: refresh_bulk_service
    return app


async def _make_client(app: FastAPI, raise_app_exceptions: bool = True) -> AsyncClient:
    """Create an httpx AsyncClient for the given FastAPI app.

    Args:
        app: The FastAPI application under test.
        raise_app_exceptions: When False the transport returns the ASGI 500
            response as an ``httpx.Response`` instead of re-raising the
            underlying exception.  Set to ``False`` when testing error paths
            that trigger ``ServerErrorMiddleware`` (e.g. unhandled
            ``RuntimeError``).

    Returns:
        An AsyncClient connected to the app via ASGITransport.
    """
    transport = ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# Background — shared Given steps
# ---------------------------------------------------------------------------


@given("the ERS REST API is running")
def api_running(ctx, monkeypatch):
    """Build the FastAPI AsyncClient with all service dependencies mocked.

    Stores ``app``, ``client``, ``lookup_service``, ``refresh_bulk_service``,
    and ``resolve_service`` in the shared context.  The ``app`` is stored so
    that individual scenarios can rebuild the client with different transport
    options (e.g. ``raise_app_exceptions=False`` for error-path scenarios).

    Args:
        ctx: Shared mutable step context.
        monkeypatch: pytest monkeypatch for environment variable injection.
    """
    lookup_svc = create_autospec(LookupService, instance=True)
    refresh_bulk_svc = create_autospec(RefreshBulkService, instance=True)
    resolve_svc = create_autospec(ResolveService, instance=True)

    app = _build_app(monkeypatch, resolve_svc, lookup_svc, refresh_bulk_svc)
    client = run_async(_make_client(app))

    ctx["app"] = app
    ctx["lookup_service"] = lookup_svc
    ctx["refresh_bulk_service"] = refresh_bulk_svc
    ctx["resolve_service"] = resolve_svc
    ctx["client"] = client


@given("the Decision Store is available")
def decision_store_available(ctx):
    """Ensure mocked services are in a healthy state (default — no exceptions).

    Args:
        ctx: Shared mutable step context.
    """
    # Services are created with create_autospec; default AsyncMocks return
    # MagicMock instances which is sufficient for the background step.
    # Individual scenarios configure specific return values in their own Givens.


# ---------------------------------------------------------------------------
# Common Then — HTTP status and error body assertions
# ---------------------------------------------------------------------------


@then(parsers.parse("the response HTTP status is {status_code:d}"))
def assert_http_status(ctx, status_code):
    """Assert the last HTTP response has the expected status code.

    Args:
        ctx: Shared mutable step context containing ``response``.
        status_code: Expected HTTP status code (integer).
    """
    assert ctx["response"].status_code == status_code


@then(parsers.parse('the response body error code is "{error_code}"'))
def response_error_code(ctx, error_code):
    """Assert the error response body contains the expected machine-readable code.

    Args:
        ctx: Shared mutable step context containing ``response``.
        error_code: Expected ``error_code`` string in the response JSON.
    """
    data = ctx["response"].json()
    assert data["error_code"] == error_code


@then("the response body contains a human-readable error message")
def response_has_error_message(ctx):
    """Assert the error response body contains a non-empty detail message.

    Args:
        ctx: Shared mutable step context containing ``response``.
    """
    data = ctx["response"].json()
    assert data.get("detail")


@then(parsers.parse('the response body error detail references "{field_name}"'))
def response_error_detail_references_field(ctx, field_name):
    """Assert the error detail string mentions the given field name.

    Args:
        ctx: Shared mutable step context containing ``response``.
        field_name: Field name that must appear in the ``detail`` string.
    """
    data = ctx["response"].json()
    detail = str(data.get("detail", ""))
    assert field_name in detail
