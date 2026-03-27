"""OTel-ready tracing foundation for the Entity Resolution Service.

This module provides a clean, minimal tracing API that:
- Uses the real OpenTelemetry SDK (api + sdk installed as dependencies)
- Is no-op by default — safe to import with no TracerProvider configured
- Never initialises global OTel state at import time
- Exposes ``span()`` and ``trace_function()`` as the only application-facing API
- Extracts span attributes from domain objects via a type registry (never raw args)

Placement convention — where to put ``@trace_function``::

    Prefer module-level public functions (the API boundary) over class methods.
    This keeps tracing at the right boundary, avoids ``self`` in the argument
    list (which the extractor registry silently ignores), and keeps the
    service class implementation detail-free.

    # Preferred — instrument the public API function:
    @trace_function(span_name="mention_parser.parse")
    def parse_entity_mention(entity_mention: EntityMention, ...) -> dict:
        service = MentionParserService(...)
        return service.parse(entity_mention)

    # Avoid — decorating the class method instead:
    class MentionParserService:
        @trace_function(span_name="mention_parser.parse")
        def parse(self, entity_mention: EntityMention) -> dict:
            ...

Usage::

    from ers.commons.adapters.tracing import configure_tracing, span, trace_function

    # In app factory or test setup — never at module level:
    configure_tracing(config)

    # In service layer — on the public function:
    @trace_function(span_name="mention_parser.parse")
    def parse_entity_mention(entity_mention: EntityMention, config: ...) -> dict:
        ...

    with span("mention_parser.extraction", fields_extracted=count):
        ...
"""

import asyncio
import functools
import logging
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider

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


def register_span_extractor(type_: type, extractor: Callable[[Any], dict[str, Any]]) -> None:
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
            except Exception:
                logger.debug("Span extractor failed for %s", type(value).__name__)
    return attributes


# ---------------------------------------------------------------------------
# Section 4 — Correlation context
# ---------------------------------------------------------------------------

_request_id_var: ContextVar[str | None] = ContextVar("ers_request_id", default=None)


def set_request_id(request_id: str | None = None) -> str:
    """Set the current ERS business-level correlation ID. Generates a UUID4 if none given.

    This is the ERS ``ResolutionRequest`` UUID — NOT the OTel trace ID.
    OTel generates its own 128-bit trace/span IDs for distributed tracing.
    This ID is the business-level correlation handle used across async call
    chains within a single resolution request.

    Call once per incoming request in HTTP middleware or the service entry point.
    Async-safe via ``contextvars`` — each task/coroutine has an isolated value.

    Args:
        request_id: ERS request UUID to propagate. A UUID4 is generated when ``None``.

    Returns:
        The request ID that was set.
    """
    rid = request_id or str(uuid.uuid4())
    _request_id_var.set(rid)
    return rid


def get_request_id() -> str | None:
    """Return the current ERS business-level correlation ID, or ``None`` if not set.

    Returns ``None`` when called outside a request context (e.g. in background tasks
    not initiated by an HTTP request). Callers should handle ``None`` gracefully.

    Returns:
        The current ERS request UUID string, or ``None``.
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
    # ``attributes or None``: an empty dict is falsy and becomes None.
    # OTel treats None and {} identically — both mean "no attributes".
    return trace.get_tracer(__name__).start_as_current_span(name, attributes=attributes or None)


def trace_function(
    func: Callable | None = None,
    *,
    span_name: str | None = None,
) -> Callable:
    """Decorator for service-layer functions. Supports both sync and async.

    Can be used with or without parentheses::

        @trace_function                              # auto span name
        @trace_function()                            # auto span name
        @trace_function(span_name="module.op")       # explicit span name

    The default span name is ``<module_file>.<qualname>``
    (e.g. ``mention_parser_service.parse_entity_mention``), derived from
    ``func.__module__`` and ``func.__qualname__``. Override with ``span_name``
    when a shorter or more intuitive name is preferred
    (e.g. ``"mention_parser.parse"``).

    Automatically extracts span attributes from typed arguments that have
    registered extractors (see ``register_span_extractor``). Arguments whose
    type has no registered extractor are silently ignored — primitives are
    never captured. This is the only attribute capture mechanism.

    ``functools.wraps`` preserves ``__name__``, ``__doc__``, and other metadata.
    Exceptions propagate unchanged; the span records the exception type and
    message.

    Args:
        func: The function to decorate. Supplied automatically when used as
              ``@trace_function`` (no parentheses); ``None`` otherwise.
        span_name: Explicit span name. Defaults to
                   ``<module_file>.<qualname>`` when omitted.

    Example::

        @trace_function
        def parse_entity_mention(entity_mention: EntityMention, ...) -> dict:
            ...

        @trace_function(span_name="mention_parser.parse")
        def parse_entity_mention(entity_mention: EntityMention, ...) -> dict:
            ...
    """

    def decorator(f: Callable) -> Callable:
        module_short = f.__module__.rsplit(".", 1)[-1]
        effective_name = span_name or f"{module_short}.{f.__qualname__}"

        if asyncio.iscoroutinefunction(f):

            @functools.wraps(f)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                attributes = _extract_attributes(args, kwargs)
                with trace.get_tracer(__name__).start_as_current_span(
                    effective_name, attributes=attributes or None
                ) as current_span:
                    try:
                        return await f(*args, **kwargs)
                    except Exception as exc:
                        current_span.set_attribute("error.type", type(exc).__name__)
                        current_span.record_exception(exc)
                        raise

            return async_wrapper

        @functools.wraps(f)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            attributes = _extract_attributes(args, kwargs)
            with trace.get_tracer(__name__).start_as_current_span(
                effective_name, attributes=attributes or None
            ) as current_span:
                try:
                    return f(*args, **kwargs)
                except Exception as exc:
                    current_span.set_attribute("error.type", type(exc).__name__)
                    current_span.record_exception(exc)
                    raise

        return sync_wrapper

    if func is not None:
        # Used as @trace_function (no parentheses)
        return decorator(func)
    return decorator


# ---------------------------------------------------------------------------
# Section 6 — Readiness hooks (stubs)
# ---------------------------------------------------------------------------


def configure_fastapi_telemetry(app: Any, config: Any) -> None:
    """Register OTel instrumentation middleware on a FastAPI application.

    Currently a no-op stub. Activate when ``opentelemetry-instrumentation-fastapi``
    is added as a dependency (``poetry add opentelemetry-instrumentation-fastapi``).

    When activated, replace the body with::

        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        if config.TRACING_ENABLED:
            FastAPIInstrumentor.instrument_app(app, tracer_provider=_provider)

    This automatically:
    - Creates a root span for every incoming HTTP request
    - Extracts W3C ``traceparent`` / ``tracestate`` from incoming headers
    - Attaches HTTP method, route, and status code as span attributes

    Call once from each app factory (``entrypoints/api/app.py``) after
    ``configure_tracing()``.

    Note:
        ``make_otel_http_headers()`` is NOT needed alongside this. When
        ``opentelemetry-instrumentation-httpx`` is also installed, outgoing
        httpx calls propagate trace context automatically.

    Args:
        app: The FastAPI application instance.
        config: ``ERSConfigResolver`` instance.
    """
