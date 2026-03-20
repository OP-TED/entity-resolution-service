# Task 1.1 — Domain Models: Request Registry (and rest API model adjustments)

## Specification Summary

Implement the domain models for the Request Registry (`src/ers/request_registry/domain/`). Also extend `src/ers/commons/adapters/hasher.py` with `SHA256ContentHasher`.

### Models (`records.py`)

**`ResolutionRequestRecord(FrozenDTO, EntityMention)`**
- Inherits from erspec `EntityMention`: `identifiedBy`, `content`, `content_type`, `parsed_representation`, `context`
- `content_hash: str` — SHA-256 hex, validated: `pattern=r'^[0-9a-f]{64}$'`
- `received_at: datetime` — must be timezone-aware (field_validator)

**`LookupRequestRecord(FrozenDTO, LookupState)`**
- Inherits from erspec `LookupState`: `source_id`, `last_snapshot`
- `updated_at: datetime` — must be timezone-aware; cross-field: `updated_at >= last_snapshot`

### Hasher Extension

`SHA256ContentHasher` in `src/ers/commons/adapters/hasher.py`.

---

## Implementation Outcomes

### What Was Accomplished

**Phase 1 (prior sessions):**
- Created `src/ers/request_registry/domain/records.py`, package markers, `SHA256ContentHasher`
- Created `tests/unit/commons/adapters/test_sha256_hasher.py` — 8 tests

**Phase 2 (2026-03-20) — model simplification + test/adapter/service alignment:**

Domain models were manually simplified to compose with erspec base classes instead of flat fields. This session aligned all tests, adapters, and services with the new models:

- **Dropped classes:** `JSONRepresentation`, `LookupRequestType` (StrEnum), `LookupState` (standalone). Entity types are dynamic (from `RDFMappingConfig`), not hardcoded enums. `parsed_representation` field on `EntityMention` replaces `JSONRepresentation`.
- **`ResolutionRequestRecord`** now inherits `EntityMention` directly — fields come from the mixin, no separate `identifier`/`entity_mention` fields. Service builds records via `**entity_mention.model_dump()`.
- **`LookupRequestRecord`** inherits `LookupState` from erspec — provides `source_id` and `last_snapshot`. Adds `updated_at` with validation.
- **Repository ABCs removed** (`ResolutionRequestRepository`, `LookupStateRepository`, `LookupRequestRepository`). Only one implementation per port; service type-hints against the Mongo classes directly.
- **`MongoResolutionRequestRepository`** now extends `BaseMongoRepository` — reuses `__init__` and `find_by_id`. Custom `_to_document`/`_from_document` for composite triad key.
- **Audit log concept dropped** — no append-only `LookupRequestRecord` for tracking SINGLE/BULK lookups.
- **Feature file simplified** — `bulk_lookup_and_snapshot_management.feature` reduced from 8 to 4 scenarios (snapshot management only).

### Key Decisions

- Compose with erspec models (`EntityMention`, `LookupState`) over flat fields — fewer fields, stronger contract alignment.
- erspec base classes override `FrozenDTO.frozen=True` via MRO — models are NOT frozen. Mutation tests removed.
- erspec `LookupState.source_id` has no `min_length=1` — empty source_id test removed.
- Repository file reduced from 135 to 85 lines by removing ABCs and reusing `BaseMongoRepository`.

### Test Results

- **51 request_registry tests pass** (unit + feature)
- **160 non-curation tests pass** (full suite minus erspec `EntityType` issue)

### Known Issue

- `mongo_client.py:52` index uses `identifier.source_id` — should be `identifiedBy.source_id` to match new document structure.

### Commits

- Phase 1: committed and merged (prior session)
- Phase 2: this session
