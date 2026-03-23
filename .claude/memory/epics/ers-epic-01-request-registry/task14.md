# Task 14: Request Registry Public API and RDF Parsing Integration

**Status:** ✅ COMPLETE — 2026-03-21
**Branch:** `feature/ERS1-144-task13` (continuing on same branch)

**Authoritative spec:** This file.

---

## What this task delivers

1. **Public module-level async functions** wrapping `RequestRegistryService` methods — the stable API boundary for other modules (entrypoints, coordinators) to call. Decorated with `@trace_function` following the OTel convention established in Task 13.

2. **RDF parsing integration** in `register_resolution_request` — new triads are parsed immediately on registration; `parsed_representation` (JSON string) is stored atomically with the record. Parsing exceptions propagate to the caller unchanged.

3. **Service simplification** — removed methods not backed by feature file scenarios (`list_resolution_requests_by_source`, `register_lookup_request`). The service surface now matches exactly what is tested and specified.

4. **Terminology cleanup** — "watermark" eliminated from all source code, docstrings, specs, and feature files. Replaced with "snapshot marker" / "snapshot state".

---

## Service surface (final)

| Method / Public function | Behaviour |
|---|---|
| `register_resolution_request(entity_mention)` | empty-check → hash → idempotency (replay/conflict) → RDF parse → store with `parsed_representation` |
| `get_resolution_request(identifier)` | fetch by triad; returns `None` if not found |
| `get_lookup_state(source_id)` | return current snapshot state; `None` if never advanced |
| `advance_snapshot(source_id, snapshot_time)` | advance bulk delta marker; raises `SnapshotRegressionError` if time regresses |

## What was removed and why

| Removed | Reason |
|---|---|
| `list_resolution_requests_by_source` | No feature file scenario. The registry is append-and-fetch-by-triad only; bulk exposure is handled by snapshot advancement, not by listing records. |
| `register_lookup_request` | Redundant with `advance_snapshot`. Bulk lookup registration IS snapshot advancement — there is no separate "register intent" step. |
| `LookupRequestType` (SINGLE/BULK) | Over-engineering. The only supported operation is bulk snapshot advancement. Single-mention fetches use `get_resolution_request` directly. |

---

## Key design decisions

### RDF config injection
`RequestRegistryService` now takes `rdf_config: RDFMappingConfig` as a required constructor argument. This keeps the parsing dependency explicit and testable (mock in unit tests, real loaded config in integration/production).

### Parsing on new triads only
Idempotent replays return the existing record (including its `parsed_representation`) without re-parsing. Parsing only happens for genuinely new triads. This preserves immutability semantics.

### `parsed_representation` — no new domain field
`EntityMention` (from erspec) already carries `parsed_representation: Optional[str]`. `ResolutionRequestRecord` inherits it. No domain model change required.

### Public function signature — service as last parameter
```python
async def register_resolution_request(
    entity_mention: EntityMention,
    service: RequestRegistryService,
) -> ResolutionRequestRecord:
```
Data first, service last — consistent with `parse_entity_mention(entity_mention, config)` from the RDF parser module.

---

## Files changed

| File | Change |
|---|---|
| `src/ers/request_registry/services/request_registry_service.py` | Add `rdf_config` to constructor; integrate RDF parsing; remove `list_by_source` and `register_lookup_request`; add 4 public functions with `@trace_function`; remove "watermark" |
| `src/ers/request_registry/adapters/records_repository.py` | Docstring: "watermark" → "snapshot state" |
| `tests/feature/request_registry/bulk_lookup_and_snapshot_management.feature` | "snapshot watermark" → "snapshot marker" / "snapshot" |
| `tests/unit/request_registry/services/test_request_registry_service.py` | Add `rdf_config` + `mock_parse_entity_mention` fixtures; pass `rdf_config` to service; apply mock to new-triad tests |
| `tests/feature/request_registry/test_resolution_request_registration.py` | Add `rdf_config` + `mock_parse_entity_mention` fixtures; wire `rdf_config` in background step; apply mock to "Register a resolution request" scenario |
| `tests/feature/request_registry/test_bulk_lookup_and_snapshot_management.py` | Add `rdf_config` fixture; wire in background step |
| `src/ers/ers_rest_api/entrypoints/api/app.py` | Wire span extractor imports at app startup |
| `src/ers/request_registry/domain/records.py` | Docstring: "watermark" → "snapshot marker" |
| `src/ers/request_registry/services/exceptions.py` | Docstring: "watermark" → "snapshot marker" |
| `.claude/memory/epics/ers-epic-01-request-registry/EPIC.md` | Full rewrite to align with implementation |

---

## Test mocking note

Unit and BDD tests for new-triad registration mock `parse_entity_mention` at the service module level. This is correct: unit tests for the service verify orchestration logic (idempotency, hashing, timestamp), not RDF parsing. RDF parsing is covered by its own test suite under `tests/unit/rdf_mention_parser/`. The `rdf_config` fixture uses a minimal valid `RDFMappingConfig` (one namespace prefix, one entity type) — enough to pass constructor validation without coupling tests to production mapping files.
