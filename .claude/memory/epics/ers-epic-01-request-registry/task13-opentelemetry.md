# Task 13: Observability Foundation

**Status:** ✅ COMPLETE — 2026-03-21 (refined 2026-03-21)
**Branch:** `feature/ERS1-144-task13`

**Authoritative spec:** `docs/superpowers/specs/2026-03-21-observability-design.md`
**Implementation plan:** `docs/superpowers/plans/2026-03-21-observability-foundation.md`

---

## What was delivered

| File | Role |
|---|---|
| `src/ers/__init__.py` | `ObservabilityConfig` mixin: `TRACING_ENABLED` + `OTEL_SERVICE_NAME` env vars |
| `src/ers/commons/adapters/tracing.py` | Core tracing module — see detailed breakdown below |
| `src/ers/commons/adapters/span_extractors.py` | Extractors for `EntityMention` + `EntityMentionIdentifier` |
| `src/ers/request_registry/adapters/span_extractors.py` | Extractor for `ResolutionRequestRecord` |
| `src/ers/rdf_mention_parser/services/mention_parser_service.py` | `parse()` accepts `EntityMention`; `@trace_function` on public function |
| `tests/unit/commons/adapters/test_tracing.py` | 23 unit tests including `InMemorySpanExporter` span name verification |
| `pyproject.toml` | `opentelemetry-api` + `opentelemetry-sdk` added |

---

## How OTel works in ERS — full picture

### 1. No-op by default

The OTel SDK is installed but does nothing until explicitly activated. Importing `tracing.py`
has zero side effects — no `TracerProvider` is set, no spans are created. The OTel API's
built-in no-op tracer handles all calls silently.

This is the opposite of the mssdk anti-pattern where `TracerProvider(...)` was called at
module level, mutating global OTel state on import.

### 2. Activation — `configure_tracing(config)`

Called once from the app factory (or test setup). Reads two env vars via `ObservabilityConfig`:

| Env var | Default | Effect |
|---|---|---|
| `TRACING_ENABLED` | `false` | `false` → no-op; `true` → activates `TracerProvider` |
| `OTEL_SERVICE_NAME` | `entity-resolution-service` | Sets the `Resource` service name on spans |

When `TRACING_ENABLED=true`:
```python
_provider = TracerProvider(resource=Resource({SERVICE_NAME: config.OTEL_SERVICE_NAME}))
trace.set_tracer_provider(_provider)
```
After this call, `trace.get_tracer(__name__)` returns a real tracer backed by the provider.

### 3. Span export — `add_span_processor(sp)`

After `configure_tracing()`, a `SpanProcessor` can be registered to export spans to a backend.
Without one, spans are created and finished but silently discarded.

```python
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
```

This is the only way to get spans to a collector (Jaeger, OTLP endpoint, etc.).

### 4. Decorating service functions — `@trace_function`

The primary instrumentation mechanism. Three equivalent forms:

```python
@trace_function                                    # auto span name: "module_file.qualname"
@trace_function()                                  # same
@trace_function(span_name="mention_parser.parse")  # explicit shorter name
```

**Auto span name** is derived from `func.__module__.rsplit(".", 1)[-1] + "." + func.__qualname__`.
For `parse_entity_mention` in `mention_parser_service.py` this gives:
`mention_parser_service.parse_entity_mention`.

**Placement rule:** Always on module-level public functions (the API boundary), not class methods.
The public function is what callers use; class methods are implementation details.

```python
# Correct
@trace_function(span_name="mention_parser.parse")
def parse_entity_mention(entity_mention: EntityMention, config: RDFMappingConfig) -> dict:
    service = MentionParserService(config, RDFParserAdapter())
    return service.parse(entity_mention)
```

The decorator:
- Creates an OTel span with the span name
- Calls `_extract_attributes()` on all arguments before entering the span
- On exception: sets `error.type` and records the exception, then re-raises unchanged
- Handles both sync and async functions via `asyncio.iscoroutinefunction()`
- Preserves `__name__`, `__doc__` via `functools.wraps`

### 5. Attribute extraction — extractor registry

`_extract_attributes(args, kwargs)` iterates every argument and checks
`_extractors.get(type(value))`. Only arguments whose **exact type** is registered contribute
span attributes. Primitives (`str`, `int`, etc.) and unregistered types are silently ignored.
`self` on class methods is silently skipped (no extractor registered for service classes).

Extractors are registered at startup by importing the `span_extractors.py` modules:

| Module | Types registered | Attributes captured |
|---|---|---|
| `commons/adapters/span_extractors.py` | `EntityMention` | `entity_mention.source_id`, `.request_id`, `.entity_type`, `.content_length` |
| `commons/adapters/span_extractors.py` | `EntityMentionIdentifier` | `entity_mention.source_id`, `.request_id`, `.entity_type` |
| `request_registry/adapters/span_extractors.py` | `ResolutionRequestRecord` | `request_registry.request_id`, `.source_id`, `.entity_type`, `.content_hash` (prefix only) |

**PII rules:** Never capture `content`, `content_type`, raw URIs, or any user-controlled string.
Use `content_length` (byte count) instead of `content`. Truncate hashes to a prefix.

Extractor modules are imported at startup, not at module level. They should be imported in the
app factory after `configure_tracing()`:
```python
import ers.commons.adapters.span_extractors           # registers EntityMention extractors
import ers.request_registry.adapters.span_extractors  # registers RequestRecord extractor
```
**This wiring is currently deferred** — neither app factory imports them yet.

### 6. Manual spans — `span()`

For tracing specific code blocks that are not full function boundaries:

```python
with span("mention_parser.extraction", fields_extracted=count):
    ...
```

No-op when no `TracerProvider` is configured. Accepts keyword attributes (caller is responsible
for PII safety).

### 7. ERS business correlation ID — `set/get_request_id()`

```python
rid = set_request_id(entity_mention.identifiedBy.request_id)  # or None → generates UUID4
rid = get_request_id()  # returns None if not set
```

**This is NOT the OTel trace ID.** OTel generates its own 128-bit trace/span IDs for
distributed tracing. This is the ERS `ResolutionRequest` UUID — a business-level handle
used to correlate logs and spans within a single resolution request.

Stored in a `ContextVar` — async-safe; each coroutine/task has its own isolated value.
Set once per incoming request in HTTP middleware or service entry points (not yet wired).

### 8. FastAPI instrumentation — `configure_fastapi_telemetry()` (stub)

Currently a no-op. When `opentelemetry-instrumentation-fastapi` is added:

```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
if config.TRACING_ENABLED:
    FastAPIInstrumentor.instrument_app(app, tracer_provider=_provider)
```

This automatically creates root spans for HTTP requests and extracts incoming W3C
`traceparent` / `tracestate` headers. Call once per app factory after `configure_tracing()`.
Outgoing httpx calls propagate trace context automatically when
`opentelemetry-instrumentation-httpx` is also installed — no manual header injection needed.

---

## Anti-patterns avoided (vs mssdk reference)

| mssdk mistake | What ERS does instead |
|---|---|
| `TracerProvider(...)` at module level | Only inside `configure_tracing()` |
| `trace.set_tracer_provider(...)` at import | Only inside `configure_tracing()` |
| `os.environ[key] = str(state)` for tracing state | `ObservabilityConfig` mixin, read-only |
| `span.set_attribute("function.args", args)` | Only registered, safe extractors; primitives ignored |
| `traced_class(cls)` — class-wide mutation | Explicit `@trace_function` per public function only |
| Decorator on class method | Decorator on public module-level function |

---

## Test isolation

OTel uses a `Once` guard (`_TRACER_PROVIDER_SET_ONCE`) that prevents `set_tracer_provider()`
being called more than once per process. Tests must reset both:

```python
trace._TRACER_PROVIDER = None
trace._TRACER_PROVIDER_SET_ONCE._done = False
```

This is done in the `reset_tracing_state` autouse fixture in `test_tracing.py`.
Never use `ProxyTracerProvider` for reset — it does not clear the guard.

---

## Deferred / not in scope

| Item | When to activate |
|---|---|
| Import extractor modules in app factories | When wiring `configure_tracing()` into app factories |
| `configure_fastapi_telemetry()` body | When adding `opentelemetry-instrumentation-fastapi` |
| OTLP exporter via `add_span_processor()` | When a real tracing backend is available |
| `set_request_id()` in HTTP middleware | When building request middleware for ERS REST API |
| Metrics (`Counter`, `Histogram`) | Out of scope for this foundation |