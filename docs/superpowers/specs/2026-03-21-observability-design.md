# Observability Foundation Design

**Date:** 2026-03-21
**Status:** Approved
**Scope:** Cross-cutting — applies to all EPICs
**Replaces:** `.claude/memory/epics/ers-epic-01-request-registry/task13-opentelemetry.md`

---

## 1. Goal

Establish a minimal, production-safe observability foundation that:

- Enables future OTel tracing without coupling business code to the OTel SDK
- Provides a clean `@trace_function()` decorator for service-layer use
- Extracts span attributes automatically from domain objects via a type registry
- Is no-op by default — safe to import with no backend configured
- Prepares FastAPI and ERE client for future OTel integration without implementing it

Do not choose or hardcode any backend, collector, or exporter at this stage.

---

## 2. Anti-patterns (learned from mssdk `comms/adapter/tracer.py`)

The mssdk implementation is a reference for what **not** to do:

| mssdk mistake | Why it's wrong | What we do instead |
|---|---|---|
| `TracerProvider(...)` at module level | Side effects on import | Explicit `configure_tracing(config)` only |
| `trace.set_tracer_provider(...)` at import | Mutates global OTel state silently | Called inside `configure_tracing()`, never at import |
| `os.environ[key] = str(state)` | Env vars as mutable runtime state | `ObservabilityConfig` Pydantic-style mixin, read-only |
| `span.set_attribute("function.args", args)` | Dumps raw args — PII risk, serialization failures | Only registered, safe extractors; primitives ignored by default |
| `traced_class(cls)` | Brittle class-wide mutation | Explicit `@trace_function()` per method only |

---

## 3. Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Number of new files | 1 generic + N extractor files | One file for infrastructure machinery; one per sub-module for domain extractors |
| File placement | `commons/adapters/tracing.py` | OTel is an infrastructure dep; adapters own infra coupling |
| Extractor placement | `<module>/adapters/span_extractors.py` | Extractors translate domain → telemetry; that is an adapter concern |
| Attribute capture default | Registered extractors only — no per-call lambdas | Safe by default; if a service takes primitives, refactor to accept the domain object |
| OTel SDK dependency | `opentelemetry-api` + `opentelemetry-sdk` added to `pyproject.toml` | Real SDK installed; no exporter yet — spans created but silently dropped until a `SpanProcessor` is registered |
| Config | `TRACING_ENABLED` + `OTEL_SERVICE_NAME` | Two env vars; service name required for `Resource` in `TracerProvider` |
| Async support | Yes — single decorator handles both | ERE client and REST APIs use async |
| `SpanAttr` constants class | Dropped | Extractor functions are the single source of truth for key names |
| Correlation ID context | Inline in `tracing.py` (4 lines) | No separate `context.py` needed at this scale |

---

## 4. Module layout

```
src/ers/
├── __init__.py                                  ← add ObservabilityConfig mixin
│
├── commons/adapters/
│   ├── tracing.py                               ← NEW: generic machinery (see §5)
│   └── span_extractors.py                       ← NEW: extractors for er-spec types
│
├── request_registry/adapters/
│   └── span_extractors.py                       ← NEW: RequestRecord extractor (EPIC-01)
│
├── rdf_mention_parser/adapters/
│   └── span_extractors.py                       ← NEW: if rdf-specific types need it (EPIC-02)
│
└── curation/adapters/
    └── span_extractors.py                       ← NEW: Decision, UserAction (EPIC-03+)
```

`tracing.py` never changes when a new domain type needs tracing. Each `span_extractors.py` evolves independently.

---

## 5. `commons/adapters/tracing.py` — full specification

Seven logical sections in one file, separated by block comments:

### 5.1 Protocol

```python
class TracerPort(Protocol):
    def start_span(self, name: str, attributes: dict[str, Any]) -> AbstractContextManager:
        ...
```

### 5.2 Imports and module-level tracer

```python
from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor
```

No `TracerPort` / `NoOpTracer` / `OtelTracer` split needed — the OTel API is no-op by default when no `TracerProvider` is set. The SDK is a real dependency, not an optional import.

### 5.3 Module state and bootstrap

```python
_provider: TracerProvider | None = None

def configure_tracing(config: Any) -> None:
    """Explicit bootstrap. Never called at import time.

    Call once from the app factory or test setup.

    Args:
        config: ERSConfigResolver instance. Reads TRACING_ENABLED and OTEL_SERVICE_NAME.
                When TRACING_ENABLED=True, creates TracerProvider with Resource and
                sets it as the global OTel provider. No SpanProcessor added yet —
                add one via add_span_processor() when a real backend is available.
    """
    global _provider
    if not config.TRACING_ENABLED:
        return
    _provider = TracerProvider(
        resource=Resource(attributes={SERVICE_NAME: config.OTEL_SERVICE_NAME})
    )
    trace.set_tracer_provider(_provider)


def add_span_processor(sp: SpanProcessor) -> None:
    """Register a SpanProcessor (e.g. BatchSpanProcessor(OTLPExporter(...))).

    No-op if configure_tracing() was not called or TRACING_ENABLED=False.
    Call after configure_tracing() to plug in an exporter.
    """
    if _provider is not None:
        _provider.add_span_processor(sp)
```

### 5.4 Extractor registry

```python
_extractors: dict[type, Callable[[Any], dict[str, Any]]] = {}

def register_span_extractor(type_: type, extractor: Callable[[Any], dict[str, Any]]) -> None:
    """Register a span attribute extractor for a domain type.

    Called from span_extractors.py modules at startup. Not called at import time.
    Later registrations for the same type overwrite earlier ones.

    Args:
        type_: The domain type to register an extractor for.
        extractor: Callable receiving one instance of type_ and returning
                   a dict of safe span attribute key-value pairs.
                   Must never capture raw content or PII.
    """
```

### 5.5 Correlation context

```python
_request_id_var: ContextVar[str | None] = ContextVar("ers_request_id", default=None)

def set_request_id(request_id: str | None = None) -> str:
    """Set the current correlation/request ID. Generates a UUID if none given."""

def get_request_id() -> str | None:
    """Get the current correlation/request ID, or None if not set."""
```

Async-safe via `contextvars`. No thread-local state.

### 5.6 Public API

#### `span()` — context manager

```python
def span(name: str, **attributes: Any):
    """Create a tracing span as a context manager.

    Delegates to trace.get_tracer(__name__).start_as_current_span().
    No-op when no TracerProvider is configured (TRACING_ENABLED=False).

    Args:
        name: Span name. Use dot-notation: 'module.operation'.
        **attributes: Explicit safe attributes to attach to the span.
                      Caller is responsible for ensuring no PII is included.

    Example:
        with span("mention_parser.extraction", fields_extracted=count):
            ...
    """
    return trace.get_tracer(__name__).start_as_current_span(
        name, attributes=attributes or None
    )
```

#### `trace_function()` — decorator

```python
def trace_function(span_name: str | None = None) -> Callable:
    """Decorator for service functions. Supports sync and async.

    Automatically extracts span attributes from typed arguments that have
    registered extractors (see register_span_extractor). Arguments with
    no registered extractor are silently ignored — primitives are never
    captured. This is the only attribute capture mechanism; there is no
    per-call lambda escape hatch by design.

    If a service function currently takes raw primitives instead of a domain
    object, refactor it to accept the appropriate domain type so the registry
    can extract attributes consistently.

    Args:
        span_name: Explicit span name. Defaults to 'module.ClassName.method_name'.

    Example:
        @trace_function(span_name="request_registry.register")
        def register(self, entity_mention: EntityMention) -> RequestRecord:
            ...

        @trace_function(span_name="mention_parser.parse")
        def parse(self, entity_mention: EntityMention) -> dict[str, Any]:
            ...
    """
```

**Async detection:** `asyncio.iscoroutinefunction(func)` — one decorator handles both.
**Metadata preservation:** `functools.wraps(func)` — `__name__`, `__doc__` preserved.
**Exception behaviour:** exceptions propagate unchanged; span records the exception type, not the message.

### 5.7 Readiness hooks

```python
def configure_fastapi_telemetry(app: Any, config: Any) -> None:
    """Registers OTel instrumentation middleware on a FastAPI application.

    Currently a no-op stub. When opentelemetry-instrumentation-fastapi is
    added as a dependency, this function will call:
        FastAPIInstrumentor.instrument_app(app, tracer_provider=_tracer.provider)

    Call once from each app factory (entrypoints/api/app.py) after configure_tracing().

    Args:
        app: The FastAPI application instance.
        config: ERSConfigResolver instance.
    """


def make_otel_http_headers() -> dict[str, str]:
    """Returns W3C trace-context propagation headers for outgoing HTTP requests.

    Currently returns an empty dict (no-op). When opentelemetry-instrumentation-httpx
    is added, this will inject the current span's traceparent and tracestate headers
    so ERE client calls participate in the distributed trace.

    Usage in ERE client adapters:
        headers = {**base_headers, **make_otel_http_headers()}
        response = httpx.post(url, headers=headers)

    Returns:
        Dict of HTTP headers to merge into outgoing requests. Empty when tracing
        is disabled or no active span exists.
    """
    return {}
```

---

## 6. `ObservabilityConfig` mixin (`ers/__init__.py`)

Follows the existing `env_property` mixin pattern exactly:

```python
class ObservabilityConfig:
    @env_property(default_value="false")
    def TRACING_ENABLED(self, v: str) -> bool:
        return v.lower() == "true"

    @env_property(default_value="entity-resolution-service")
    def OTEL_SERVICE_NAME(self, v: str) -> str:
        return v
```

`ERSConfigResolver` extends `ObservabilityConfig` alongside the existing mixins.
Two env vars. `TRACING_ENABLED=true` activates the OTel `TracerProvider`.
`OTEL_SERVICE_NAME` sets the `Resource` service name (defaults to `"entity-resolution-service"`).

---

## 7. Extractor files — structure and convention

Each `span_extractors.py` follows this pattern:

```python
# ers/commons/adapters/span_extractors.py
from erspec.models.ere import EntityMention, EntityMentionIdentifier
from ers.commons.adapters.tracing import register_span_extractor

register_span_extractor(
    EntityMention,
    lambda m: {
        "entity_mention.source_id":      m.identifier.source_id,
        "entity_mention.request_id":     str(m.identifier.request_id),
        "entity_mention.entity_type":    str(m.identifier.entity_type),
        "entity_mention.content_length": len(m.content.encode("utf-8")),
        # Never: m.content, m.content_type — PII/size risk
    }
)

register_span_extractor(
    EntityMentionIdentifier,
    lambda i: {
        "entity_mention.source_id":   i.source_id,
        "entity_mention.request_id":  str(i.request_id),
        "entity_mention.entity_type": str(i.entity_type),
    }
)
```

**Conventions:**
- Attribute key format: `<domain_concept>.<snake_case_field>` — no free strings
- Never capture raw content, raw URIs beyond identifiers, or any field that could be PII
- One `register_span_extractor()` call per type — later registrations overwrite earlier
- No business logic in extractors — pure field projection

**Activation:** extractor modules are imported at startup (app factory or test fixture), not at module import time.

---

## 8. Per-epic application guide

### EPIC-01 — Request Registry

**New file:** `src/ers/request_registry/adapters/span_extractors.py`

Extractor for `RequestRecord` (or its identifier type once defined). Sample attributes:
- `request_registry.request_id`
- `request_registry.source_id`
- `request_registry.entity_type`
- `request_registry.status`

**Decorate:** `RequestRegistryService` methods that register, update, and retrieve records.

### EPIC-02 — RDF Mention Parser

**Signature refactor required.** `MentionParserService.parse(content, content_type, entity_type)`
currently takes raw strings. It must be refactored to accept `EntityMention` directly so the
registered extractor in `commons/adapters/span_extractors.py` can extract span attributes
automatically — consistent with every other service in the system.

Refactored signature:

```python
@trace_function(span_name="mention_parser.parse")
def parse(self, entity_mention: EntityMention) -> dict[str, Any]:
    content       = entity_mention.content
    content_type  = entity_mention.content_type
    entity_type   = str(entity_mention.identifier.entity_type)
    ...
```

The `EntityMention` extractor (registered in `commons/adapters/span_extractors.py`) provides:
- `entity_mention.source_id`, `entity_mention.request_id`, `entity_mention.entity_type`
- `entity_mention.content_length`

No lambda, no `safe_attrs`, no `rdf_mention_parser/adapters/span_extractors.py` needed.

The public function `parse_entity_mention()` already accepts separate primitives — it should
also be refactored to accept `EntityMention` and delegate to the updated service method.

### EPIC-03+ — Curation / Decision

**New file:** `src/ers/curation/adapters/span_extractors.py`

Extractor for `Decision`, `UserAction`. Sample attributes:
- `decision.decision_id`
- `decision.cluster_id`
- `decision.entity_type`
- `decision.action` (MERGE / SPLIT / EXCLUDE)

**Decorate:** `DecisionCurationService`, `UserActionService` methods.

### ERE Client / Resolution Coordinator

`make_otel_http_headers()` called in each outgoing HTTP request in the ERE adapter. When real OTel propagation is activated, trace context flows into the ERE engine automatically.

### FastAPI Entrypoints (Curation API + ERS REST API)

`configure_fastapi_telemetry(app, config)` called once in each app factory after `configure_tracing(config)`. Root spans for HTTP requests will be created automatically by OTel middleware when activated.

---

## 9. Testing requirements

**`tests/unit/commons/adapters/test_tracing.py`**

| Test | What it verifies |
|---|---|
| `span()` no-op | Does not raise; no side effects |
| `trace_function()` sync no-op | Decorated function returns correct value |
| `trace_function()` async no-op | Decorated async function returns correct value |
| Exception propagation | Exception inside decorated function propagates unchanged |
| `functools.wraps` | `__name__` preserved on decorated function |
| `configure_tracing()` explicit | Importing module does not activate tracing; only `configure_tracing()` does |
| Extractor auto-extraction | Registered type → extractor called; primitives → ignored |
| `safe_attrs` fallback | Callable invoked; attributes passed to tracer |
| `safe_attrs=None` default | No attributes captured |
| Correlation ID isolation | `set_request_id()` / `get_request_id()` isolated between async contexts |
| OTel absent | Importing module without `opentelemetry-sdk` installed does not raise |

---

## 10. What is explicitly deferred

- Adding `opentelemetry-sdk` to `pyproject.toml` (done when a real backend is needed)
- Implementing `configure_fastapi_telemetry()` beyond stub
- Implementing `make_otel_http_headers()` beyond returning `{}`
- Log enrichment with trace/span IDs (requires active OTel span, deferred with backend)
- Metrics (`Counter`, `Histogram`) — not in scope for this foundation
