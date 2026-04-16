"""Unit tests for ers.commons.adapters.tracing.

Covers: no-op behaviour, configure_tracing bootstrap, extractor registry,
trace_function decorator (sync + async), span context manager,
exception propagation, and correlation ID context.
"""

import asyncio
from unittest.mock import MagicMock

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

import ers.commons.adapters.tracing as tracing_module
from ers.commons.adapters.tracing import (
    add_span_processor,
    configure_tracing,
    get_extractor,
    get_request_id,
    register_span_extractor,
    set_request_id,
    span,
    trace_function,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _reset_otel_globals() -> None:
    """Reset OTel global tracer provider state for test isolation.

    OTel uses a ``Once`` guard (``_TRACER_PROVIDER_SET_ONCE``) that prevents
    ``set_tracer_provider()`` from being called more than once per process.
    We reset both the provider reference and the ``Once._done`` flag directly —
    this is the same approach used in the OTel Python SDK's own test suite.
    """
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def reset_tracing_state():
    """Reset module and OTel global state before and after each test."""
    original_provider = tracing_module._provider
    original_extractors = dict(tracing_module._extractors)
    tracing_module._provider = None
    tracing_module._extractors.clear()
    _reset_otel_globals()
    yield
    tracing_module._provider = original_provider
    tracing_module._extractors.clear()
    tracing_module._extractors.update(original_extractors)
    _reset_otel_globals()


def _make_config(enabled: bool = False, service_name: str = "test-service") -> MagicMock:
    cfg = MagicMock()
    cfg.TRACING_ENABLED = enabled
    cfg.OTEL_SERVICE_NAME = service_name
    cfg.OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4318/v1/traces"
    return cfg


# ---------------------------------------------------------------------------
# span() — context manager
# ---------------------------------------------------------------------------


def test_span_noop_does_not_raise():
    with span("test.operation"):
        pass


def test_span_with_attributes_does_not_raise():
    with span("test.operation", count=5, flag=True):
        pass


# ---------------------------------------------------------------------------
# trace_function() — sync
# ---------------------------------------------------------------------------


def test_trace_function_sync_returns_correct_value():
    @trace_function(span_name="test.sync")
    def add(a, b):
        return a + b

    assert add(2, 3) == 5


def test_trace_function_preserves_function_name():
    @trace_function(span_name="test.meta")
    def my_function():
        """My docstring."""

    assert my_function.__name__ == "my_function"
    assert my_function.__doc__ == "My docstring."


def test_trace_function_no_parens():
    """@trace_function without parentheses must work identically to @trace_function()."""

    @trace_function
    def standalone():
        return "ok"

    assert standalone() == "ok"
    assert standalone.__name__ == "standalone"


def test_trace_function_default_span_name_uses_module_and_qualname():
    """Default span name is <module_file>.<qualname> — verified via exported span."""
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    configure_tracing(_make_config(enabled=True))
    tracing_module._provider.add_span_processor(SimpleSpanProcessor(exporter))

    @trace_function
    def my_operation():
        pass

    my_operation()

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    # Module file is "test_tracing", qualname is "test_trace_function_default_span_name_uses_module_and_qualname.<locals>.my_operation"
    assert spans[0].name.startswith("test_tracing.")
    assert spans[0].name.endswith(".my_operation")


def test_trace_function_sync_exception_propagates():
    @trace_function(span_name="test.raises")
    def boom():
        raise ValueError("intentional")

    with pytest.raises(ValueError, match="intentional"):
        boom()


# ---------------------------------------------------------------------------
# trace_function() — async
# ---------------------------------------------------------------------------


def test_trace_function_async_returns_correct_value():
    @trace_function(span_name="test.async")
    async def async_add(a, b):
        return a + b

    result = asyncio.run(async_add(3, 4))
    assert result == 7


def test_trace_function_async_exception_propagates():
    @trace_function(span_name="test.async_raises")
    async def async_boom():
        raise RuntimeError("async error")

    with pytest.raises(RuntimeError, match="async error"):
        asyncio.run(async_boom())


def test_trace_function_async_preserves_name():
    @trace_function()
    async def my_async_fn():
        pass

    assert my_async_fn.__name__ == "my_async_fn"


# ---------------------------------------------------------------------------
# configure_tracing() — bootstrap
# ---------------------------------------------------------------------------


def test_import_does_not_activate_tracing():
    """_provider must be None at import time — no side effects on import."""
    assert tracing_module._provider is None


def test_configure_tracing_disabled_leaves_provider_none():
    configure_tracing(_make_config(enabled=False))
    assert tracing_module._provider is None


def test_configure_tracing_enabled_sets_provider():
    configure_tracing(_make_config(enabled=True, service_name="ers-test"))
    assert isinstance(tracing_module._provider, TracerProvider)


def test_configure_tracing_enabled_registers_global_provider():
    configure_tracing(_make_config(enabled=True, service_name="ers-test"))
    assert trace.get_tracer_provider() is tracing_module._provider


# ---------------------------------------------------------------------------
# add_span_processor()
# ---------------------------------------------------------------------------


def test_add_span_processor_noop_when_not_configured():
    mock_processor = MagicMock()
    add_span_processor(mock_processor)  # Must not raise


def test_add_span_processor_registers_when_configured():
    configure_tracing(_make_config(enabled=True))
    mock_processor = MagicMock()
    tracing_module._provider.add_span_processor = MagicMock()
    add_span_processor(mock_processor)
    tracing_module._provider.add_span_processor.assert_called_once_with(mock_processor)


# ---------------------------------------------------------------------------
# Extractor registry
# ---------------------------------------------------------------------------


class _SampleDomain:
    def __init__(self, value: str):
        self.value = value


def test_extractor_called_for_registered_type():
    extractor = MagicMock(return_value={"sample.value": "hello"})
    register_span_extractor(_SampleDomain, extractor)

    @trace_function(span_name="test.extractor")
    def service_fn(domain_obj: _SampleDomain) -> str:
        return domain_obj.value

    domain_obj = _SampleDomain("hello")
    result = service_fn(domain_obj)
    assert result == "hello"
    extractor.assert_called_once_with(domain_obj)


def test_unregistered_type_silently_ignored():
    @trace_function(span_name="test.no_extractor")
    def fn(x: int) -> int:
        return x * 2

    assert fn(5) == 10


def test_later_registration_overwrites_earlier():
    register_span_extractor(_SampleDomain, lambda o: {"key": "first"})
    register_span_extractor(_SampleDomain, lambda o: {"key": "second"})
    extractor = get_extractor(_SampleDomain)
    assert extractor is not None
    assert extractor(_SampleDomain("x")) == {"key": "second"}


# ---------------------------------------------------------------------------
# Correlation context
# ---------------------------------------------------------------------------


def test_set_and_get_request_id():
    rid = set_request_id("req-123")
    assert rid == "req-123"
    assert get_request_id() == "req-123"


def test_set_request_id_generates_uuid_when_none():
    rid = set_request_id()
    assert len(rid) == 36  # UUID4 format
    assert get_request_id() == rid


def test_get_request_id_returns_none_when_not_set():
    tracing_module._request_id_var.set(None)
    assert get_request_id() is None


def test_request_id_isolation_between_async_contexts():
    """set_request_id() in one async context must not bleed into another."""

    async def coroutine_a() -> str:
        return set_request_id("context-a")

    async def coroutine_b() -> str | None:
        tracing_module._request_id_var.set(None)
        return get_request_id()

    id_a = asyncio.run(coroutine_a())
    id_b = asyncio.run(coroutine_b())

    assert id_a == "context-a"
    assert id_b is None
