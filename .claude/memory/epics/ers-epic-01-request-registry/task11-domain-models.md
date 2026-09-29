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

---

## PR Review Comments Summary (2026-03-21)

### PR #22 — `feat(request-registry): EPIC-01 Request Registry implementation`

**No review comments received.** PR has not been reviewed yet.

### PR #20 — `feat/ers rest api`

**WIP PR, no review comments.**

### PR #19 — `feat(ERS1-142): EPIC-02 tasks 4-5 — global config + RDF mention parser service`

This PR is EPIC-02 scope but contains comments relevant to shared code and patterns also used by EPIC-01.

#### Copilot comments (2 items)

1. **Multi-entity detection is unreliable** (`mention_parser_service.py:126`)
   - `len(rows) > 1` incorrectly flags multi-valued properties (cartesian products from OPTIONAL patterns) as multiple entities. Should use `COUNT(DISTINCT ?entity)` or aggregate field values.
   - **Status:** Not addressed — EPIC-02 scope, not related to EPIC-01.
   - **Should be addressed:** Yes, in EPIC-02 follow-up. Valid bug.

2. **Docstring contradicts behaviour** (`mention_parser_service.py:61`)
   - Class docstring says "no partial results" but `parse()` returns `None` for absent fields (partial extraction is allowed).
   - **Status:** Not addressed — EPIC-02 scope.
   - **Should be addressed:** Yes, minor docstring fix in EPIC-02.

#### gkostkowski comments (4 items)

3. **Obscure `inspect` invocation in `config_resolver.py:14`**
   - Requested extracting to a meaningful utility function or adding an explanatory comment.
   - **Status:** Not addressed.
   - **Should be addressed:** Yes, in EPIC-02 or commons follow-up. Improves readability.

4. **`[ENV]` logging specifier convention** (`config_resolver.py:32`)
   - Side comment about aligning on how to use extra specifiers/suffixes in log lines for context.
   - **Status:** Not addressed — acknowledged as future alignment topic.
   - **Should be addressed:** Not urgent. Track as a convention discussion.

5. **Working directory for default config path** (`ers/__init__.py:79`)
   - Suggested commenting on what working directory resolves the default absolute path, but noted the comment belongs in infra docs rather than code.
   - **Status:** Not addressed.
   - **Should be addressed:** Low priority. Better suited for infra/deployment docs.

6. **`TEST_ROOT_DIR` in conftest** (`test_parser_configuration.py:32`)
   - Proposed introducing a shared `TEST_ROOT_DIR` constant in a conftest file instead of repeating path construction in each test file.
   - **Status:** Not addressed.
   - **Should be addressed:** Yes — applies across all test files including EPIC-01 tests. Good DRY improvement.

### Summary

| # | Comment | Scope | Addressed | Action needed |
|---|---------|-------|-----------|---------------|
| 1 | Multi-entity detection bug | EPIC-02 | No | Fix in EPIC-02 |
| 2 | Docstring contradiction | EPIC-02 | No | Fix in EPIC-02 |
| 3 | Obscure inspect invocation | commons | No | Fix in EPIC-02/commons |
| 4 | Logging specifier convention | commons | No | Future convention alignment |
| 5 | Default config path docs | infra | No | Low priority, infra docs |
| 6 | TEST_ROOT_DIR in conftest | cross-cutting | No | Apply across all test files |
