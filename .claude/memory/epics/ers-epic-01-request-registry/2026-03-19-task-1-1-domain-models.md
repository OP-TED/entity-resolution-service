# Task 1.1 — Domain Models: Request Registry

## Task Description

Implement the domain models for the Request Registry (`src/ers/request_registry/domain/`).
All models are immutable Pydantic records (frozen). No I/O, no service logic, no framework deps.
Also extend `src/ers/commons/adapters/hasher.py` with `SHA256ContentHasher`.

## Acceptance Criteria

1. `from ers.request_registry.domain.records import ResolutionRequestRecord` works.
2. All four models instantiate with valid data and reject invalid data (Pydantic validation).
3. Frozen models raise `ValidationError` on mutation attempt.
4. `SHA256ContentHasher().hash("")` returns `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
5. `SHA256ContentHasher().verify(content, hash)` returns `True` for matching pairs, `False` otherwise.
6. `LookupRequestType.SINGLE` and `LookupRequestType.BULK` are valid string-comparable values.
7. Unit tests cover all four models and the hash helper.

## Gherkin Scenarios

Not directly covered by BDD features (domain models are internal building blocks). Covered by unit tests per the spec.

## Layers Affected

- `src/ers/request_registry/domain/` — new sub-module, domain layer
- `src/ers/commons/adapters/hasher.py` — adapter layer, additive change

---
<!-- implementation-log -->
---

## Implementation Log

### What Was Accomplished

- Created `src/ers/request_registry/__init__.py` (empty package marker)
- Created `src/ers/request_registry/domain/__init__.py` (empty package marker)
- Created `src/ers/request_registry/domain/records.py` with:
  - `LookupRequestType(StrEnum)` — SINGLE and BULK values
  - `JSONRepresentation(FrozenDTO)` — thin wrapper for parsed JSON dict
  - `ResolutionRequestRecord(FrozenDTO)` — immutable intake record with identifier, entity_mention, content_hash, received_at, json_representation
  - `LookupRequestRecord(FrozenDTO)` — append-only lookup audit record
  - `LookupState(FrozenDTO)` — per-source watermark for bulk synchronisation
- Extended `src/ers/commons/adapters/hasher.py` with `SHA256ContentHasher` implementing the `ContentHasher` ABC via `hashlib.sha256`
- Created `tests/unit/commons/adapters/test_sha256_hasher.py` — 8 tests for the hasher
- Created `tests/unit/request_registry/domain/test_records.py` — 27 tests across all 5 model types
- Total: 35 new tests, all pass. Full unit suite: 276/276 pass.

### Key Decisions

- `LookupRequestType` uses `StrEnum` (consistent with `ResolutionOutcome` in commons), not `str, Enum` as shown in the EPIC spec overview. The task spec (`task11.md`) is authoritative here and explicitly requires `StrEnum`.
- `SHA256ContentHasher` added as a new class in the existing `hasher.py` — no existing classes modified, blast radius is zero.
- `records.py` imports only from stdlib, erspec, and `ers.commons.domain.data_transfer_objects` — no import from services, adapters (other than the base class in commons.domain), or entrypoints.
- All fields decorated with `Field(..., description="...")` consistent with the REST API domain style.

### Deviations from Spec

None. Implementation follows the task spec (`task11.md`) exactly.

### Commits

Pending developer approval.
