"""OTel-ready tracing foundation for the Entity Resolution Service.

This module provides a clean, minimal tracing API that:
- Uses the real OpenTelemetry SDK (api + sdk installed as dependencies)
- Is no-op by default — safe to import with no TracerProvider configured
- Never initialises global OTel state at import time
- Exposes ``span()`` and ``trace_function()`` as the only application-facing API
- Extracts span attributes from domain objects via a type registry (never raw args)

Usage::

    from ers.commons.adapters.tracing import configure_tracing, span, trace_function

    # In app factory or test setup — never at module level:
    configure_tracing(config)

    # In service layer:
    @trace_function(span_name="request_registry.register")
    def register(self, entity_mention: EntityMention) -> RequestRecord:
        ...

    with span("mention_parser.extraction", fields_extracted=count):
        ...
"""

import asyncio
import functools
import logging
import uuid
from contextvars import ContextVar
from typing import Any, Callable

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section 1 — Module state
# ---------------------------------------------------------------------------

_provider: TracerProvider | None = None

# ---------------------------------------------------------------------------
# Section 2 — Bootstrap
# ---------------------------------------------------------------------------


def configure_tracing(config: Any) -> None:
    """Explicit bootstrap. Never called at import time.

    Call once from the app factory or test setup.
    When ``TRACING_ENABLED=False`` (default), this is a no-op and the OTel API
    remains in its built-in no-op state — no spans are created or exported.

    Args:
        config: ``ERSConfigResolver`` instance. Reads ``TRACING_ENABLED`` and
                ``OTEL_SERVICE_NAME``.
    """
    global _provider
    if not config.TRACING_ENABLED:
        return
    _provider = TracerProvider(
        resource=Resource(attributes={SERVICE_NAME: config.OTEL_SERVICE_NAME})
    )
    trace.set_tracer_provider(_provider)
    logger.info("OTel tracing configured: service=%s", config.OTEL_SERVICE_NAME)


def add_span_processor(sp: SpanProcessor) -> None:
    """Register a SpanProcessor with the active TracerProvider.

    Use this to plug in an exporter after ``configure_tracing()`` has been called,
    for example::

        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    No-op when ``configure_tracing()`` was not called (``TRACING_ENABLED=False``).

    Args:
        sp: A ``SpanProcessor`` instance to register.
    """
    if _provider is not None:
        _provider.add_span_processor(sp)


# ---------------------------------------------------------------------------
# Section 3 — Extractor registry
# ---------------------------------------------------------------------------

_extractors: dict[type, Callable[[Any], dict[str, Any]]] = {}


def register_span_extractor(
    type_: type, extractor: Callable[[Any], dict[str, Any]]
) -> None:
    """Register a span attribute extractor for a domain type.

    Called from ``span_extractors.py`` modules at startup — never at import time.
    Later registrations for the same type overwrite earlier ones.

    Extractor functions must:
    - Return only safe, non-PII attributes
    - Never capture raw content, large payloads, or user-controlled strings
    - Use attribute key format ``domain_concept.snake_case_field``

    Args:
        type_: The domain type to register an extractor for.
        extractor: Callable that receives one instance of ``type_`` and returns
                   a dict of safe span attribute key-value pairs.
    """
    _extractors[type_] = extractor


def _extract_attributes(args: tuple, kwargs: dict) -> dict[str, Any]:
    """Extract span attributes from call arguments using registered extractors.

    Only arguments whose exact type has a registered extractor contribute
    attributes. Primitives, unregistered types, and ``self``/``cls`` are
    silently ignored.

    Args:
        args: Positional arguments from the decorated function call.
        kwargs: Keyword arguments from the decorated function call.

    Returns:
        Merged dict of safe span attributes, or empty dict if none matched.
    """
    attributes: dict[str, Any] = {}
    for value in (*args, *kwargs.values()):
        extractor = _extractors.get(type(value))
        if extractor is not None:
            try:
                attributes.update(extractor(value))
            except Exception:  # noqa: BLE001
                logger.debug("Span extractor failed for %s", type(value).__name__)
    return attributes


# ---------------------------------------------------------------------------
# Section 4 — Correlation context
# ---------------------------------------------------------------------------

_request_id_var: ContextVar[str | None] = ContextVar("ers_request_id", default=None)


def set_request_id(request_id: str | None = None) -> str:
    """Set the current correlation/request ID. Generates a UUID4 if none given.

    Async-safe via ``contextvars`` — each task/coroutine has an isolated value.

    Args:
        request_id: ID to set. A UUID4 string is generated when ``None``.

    Returns:
        The request ID that was set.
    """
    rid = request_id or str(uuid.uuid4())
    _request_id_var.set(rid)
    return rid


def get_request_id() -> str | None:
    """Return the current correlation/request ID, or ``None`` if not set.

    Returns:
        The current request ID string, or ``None``.
    """
    return _request_id_var.get()


# ---------------------------------------------------------------------------
# Section 5 — Public API: span() and trace_function()
# ---------------------------------------------------------------------------


def span(name: str, **attributes: Any):
    """Create a tracing span as a context manager.

    Delegates to ``trace.get_tracer(__name__).start_as_current_span()``.
    No-op when no ``TracerProvider`` is configured (``TRACING_ENABLED=False``).

    Args:
        name: Span name. Use dot-notation: ``'module.operation'``.
        **attributes: Explicit safe attributes to attach to the span.
                      Caller is responsible for ensuring no PII is included.

    Example::

        with span("mention_parser.extraction", fields_extracted=count):
            ...
    """
    return trace.get_tracer(__name__).start_as_current_span(
        name, attributes=attributes or None
    )


def trace_function(span_name: str | None = None) -> Callable:
    """Decorator for service-layer functions. Supports both sync and async.

    Automatically extracts span attributes from typed arguments that have
    registered extractors (see ``register_span_extractor``). Arguments whose
    type has no registered extractor are silently ignored — primitives are
    never captured. This is the only attribute capture mechanism.

    ``functools.wraps`` preserves ``__name__``, ``__doc__``, and other metadata.
    Exceptions propagate unchanged; the span records the exception type only
    (never the message, to avoid capturing PII).

    Args:
        span_name: Explicit span name. Defaults to ``func.__qualname__``
                   (e.g. ``"RequestRegistryService.register"``).

    Example::

        @trace_function(span_name="request_registry.register")
        def register(self, entity_mention: EntityMention) -> RequestRecord:
            ...
    """
    def decorator(func: Callable) -> Callable:
        effective_name = span_name or func.__qualname__

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                attributes = _extract_attributes(args, kwargs)
                with trace.get_tracer(__name__).start_as_current_span(
                    effective_name, attributes=attributes or None
                ) as current_span:
                    try:
                        return await func(*args, **kwargs)
                    except Exception as exc:
                        current_span.set_attribute("error.type", type(exc).__name__)
                        current_span.record_exception(exc)
                        raise
            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            attributes = _extract_attributes(args, kwargs)
            with trace.get_tracer(__name__).start_as_current_span(
                effective_name, attributes=attributes or None
            ) as current_span:
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    current_span.set_attribute("error.type", type(exc).__name__)
                    current_span.record_exception(exc)
                    raise
        return sync_wrapper

    return decorator


# ---------------------------------------------------------------------------
# Section 6 — Readiness hooks (stubs)
# ---------------------------------------------------------------------------


def configure_fastapi_telemetry(app: Any, config: Any) -> None:
    """Register OTel instrumentation middleware on a FastAPI application.

    Currently a no-op stub. When ``opentelemetry-instrumentation-fastapi`` is
    added as a dependency, this function will call::

        FastAPIInstrumentor.instrument_app(app, tracer_provider=_provider)

    Call once from each app factory (``entrypoints/api/app.py``) after
    ``configure_tracing()``.

    Args:
        app: The FastAPI application instance.
        config: ``ERSConfigResolver`` instance.
    """


def make_otel_http_headers() -> dict[str, str]:
    """Return W3C trace-context propagation headers for outgoing HTTP requests.

    Currently returns an empty dict (no-op). When
    ``opentelemetry-instrumentation-httpx`` is added, this will inject the
    current span's ``traceparent`` and ``tracestate`` headers so ERE client
    calls participate in the distributed trace.

    Usage in ERE client adapters::

        headers = {**base_headers, **make_otel_http_headers()}
        response = httpx.post(url, headers=headers)

    Returns:
        Dict of HTTP headers to merge into outgoing requests. Empty when
        tracing is disabled or no active span exists.
    """
    return {}
