# Observability Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add minimal OTel-ready tracing infrastructure to ERS — no-op by default, decorator-driven, type-registry-based attribute extraction.

**Architecture:** Single `commons/adapters/tracing.py` file with Protocol + NoOpTracer + OtelTracer stub + extractor registry + correlation context + `span()` + `trace_function()`. Per-sub-module `span_extractors.py` files register domain type extractors at startup.

**Tech Stack:** Python stdlib only (`contextvars`, `functools`, `asyncio`). Optional `opentelemetry-sdk` guarded by `try/except`.

**Spec:** `docs/superpowers/specs/2026-03-21-observability-design.md`

---

### Task 1: `ObservabilityConfig` mixin

**Files:**
- Modify: `src/ers/__init__.py`
- Test: `tests/unit/commons/adapters/test_app_config.py` (or new `test_observability_config.py`)

- [ ] Write failing test: `TRACING_ENABLED` defaults to `False`, reads `"true"` as `True`
- [ ] Run test — expect FAIL
- [ ] Add `ObservabilityConfig` mixin class to `src/ers/__init__.py`; add it to `ERSConfigResolver` bases
- [ ] Run tests — expect PASS
- [ ] Commit: `feat: add TRACING_ENABLED config property to ERSConfigResolver`

---

### Task 2: Core `tracing.py` — no-op path + API

**Files:**
- Create: `src/ers/commons/adapters/tracing.py`
- Create: `tests/unit/commons/adapters/test_tracing.py`

- [ ] Write failing tests (all no-op path, see spec §9):
  - `span()` does not raise
  - `trace_function()` sync — returns correct value, preserves `__name__`
  - `trace_function()` async — returns correct value
  - exception inside decorated fn propagates unchanged
  - importing module does not activate tracing (no side effects)
  - `configure_tracing()` explicit call activates; import does not
  - `set_request_id()` / `get_request_id()` isolated between async contexts
- [ ] Run tests — expect FAIL
- [ ] Implement `tracing.py` (all 7 sections from spec §5): `TracerPort`, `NoOpTracer`, `OtelTracer` stub, `_tracer` module state, `configure_tracing()`, `_extractors` registry + `register_span_extractor()`, `_request_id_var` + `set/get_request_id()`, `span()`, `trace_function()`, `configure_fastapi_telemetry()` stub, `make_otel_http_headers()` stub
- [ ] Run tests — expect PASS
- [ ] Commit: `feat: add commons/adapters/tracing.py with no-op OTel foundation`

---

### Task 3: Extractor registry tests

**Files:**
- Modify: `tests/unit/commons/adapters/test_tracing.py`

- [ ] Add tests: registered type → extractor called; unregistered type / primitives → silently ignored
- [ ] Run — expect FAIL
- [ ] Implementation is already done (registry in tracing.py); just verify extractor is invoked in `trace_function`
- [ ] Run — expect PASS
- [ ] Commit: `test: add extractor registry tests for trace_function`

---

### Task 4: `commons/adapters/span_extractors.py`

**Files:**
- Create: `src/ers/commons/adapters/span_extractors.py`

- [ ] Implement extractors for `EntityMention` and `EntityMentionIdentifier` per spec §7
- [ ] Manually verify: import module, call `get_request_id()`, check no crash
- [ ] Commit: `feat: add span extractors for EntityMention and EntityMentionIdentifier`

---

### Task 5: `request_registry/adapters/span_extractors.py`

**Files:**
- Create: `src/ers/request_registry/adapters/span_extractors.py`

- [ ] Implement extractor for `ResolutionRequestRecord` per spec §8 (fields: `request_registry.request_id`, `source_id`, `entity_type`, `status`)
- [ ] Commit: `feat: add span extractor for ResolutionRequestRecord`

---

### Task 6: Refactor `MentionParserService.parse()` to accept `EntityMention`

**Files:**
- Modify: `src/ers/rdf_mention_parser/services/mention_parser_service.py`
- Modify: `tests/unit/rdf_mention_parser/services/test_mention_parser_service.py`
- Modify: `tests/feature/rdf_mention_parser/test_rdf_parsing.py`

> This is a breaking change. Update tests first so the suite is red, then fix the implementation.

- [ ] Update unit test `service` fixture and all `service.parse(...)` calls to construct `EntityMention` and pass it
- [ ] Update feature step functions `parse_mention_default_uri` and `parse_mention_with_uri` (lines ~322, ~336) to build `EntityMention` from `ctx` fields
- [ ] Update `parse_entity_mention()` public function signature to accept `EntityMention`
- [ ] Run tests — expect FAIL
- [ ] Refactor `MentionParserService.parse(self, entity_mention: EntityMention)` — extract `content`, `content_type`, `entity_type` from the object; add `@trace_function(span_name="mention_parser.parse")` decorator
- [ ] Run all tests — expect PASS (`make test` or `pytest tests/unit/rdf_mention_parser tests/feature/rdf_mention_parser`)
- [ ] Commit: `refactor: MentionParserService.parse() accepts EntityMention; add trace_function decorator`

---

## Run full suite

```bash
make test
```

Expected: all existing tests pass + new tracing tests pass.
