# Task 13: Observability Foundation

**Status:** ✅ COMPLETE — 2026-03-21
**Branch:** `feature/ERS1-144-task13`

**Authoritative spec:** `docs/superpowers/specs/2026-03-21-observability-design.md`
**Implementation plan:** `docs/superpowers/plans/2026-03-21-observability-foundation.md`

---

## What was delivered

| File | Role |
|---|---|
| `src/ers/__init__.py` | `ObservabilityConfig` mixin: `TRACING_ENABLED` + `OTEL_SERVICE_NAME` |
| `src/ers/commons/adapters/tracing.py` | Real OTel SDK: `configure_tracing()`, `add_span_processor()`, `span()`, `trace_function()`, extractor registry, correlation context |
| `src/ers/commons/adapters/span_extractors.py` | `EntityMention` + `EntityMentionIdentifier` extractors |
| `src/ers/request_registry/adapters/span_extractors.py` | `ResolutionRequestRecord` extractor |
| `src/ers/rdf_mention_parser/services/mention_parser_service.py` | `parse()` refactored to accept `EntityMention`; `@trace_function` applied |
| `tests/unit/commons/adapters/test_tracing.py` | 22 unit tests |
| `pyproject.toml` | `opentelemetry-api` + `opentelemetry-sdk` added |

## Key design decisions (vs original spec)

- Real `opentelemetry-api` + `opentelemetry-sdk` installed — not stubs
- `TracerProvider` created only inside `configure_tracing()` — never at import time
- `add_span_processor(sp)` exposes future exporter plug-in point
- `TRACING_ENABLED` + `OTEL_SERVICE_NAME` — two env vars (original had one)
- No `traced_class`, no raw arg capture, no `SpanAttr` constants
- Extractor registry (`register_span_extractor`) is the only attribute capture mechanism
- `MentionParserService.parse(content, content_type, entity_type)` → `parse(entity_mention: EntityMention)`
- OTel test isolation: reset `trace._TRACER_PROVIDER = None` AND `trace._TRACER_PROVIDER_SET_ONCE._done = False`

## To add a real exporter (future)

```python
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
```