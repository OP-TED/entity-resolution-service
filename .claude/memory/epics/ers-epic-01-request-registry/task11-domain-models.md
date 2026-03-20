# Task 1.1 — Domain Models: Request Registry

## Specification Summary

Implement the domain models for the Request Registry (`src/ers/request_registry/domain/`). All models are immutable Pydantic records (frozen). No I/O, no service logic, no framework deps. Also extend `src/ers/commons/adapters/hasher.py` with `SHA256ContentHasher`.

### Files to Create/Modify

- Create: `src/ers/request_registry/domain/records.py`
- Create: `src/ers/request_registry/__init__.py`, `src/ers/request_registry/domain/__init__.py`
- Extend: `src/ers/commons/adapters/hasher.py` — add `SHA256ContentHasher`

### Models (`records.py`)

All inherit `FrozenDTO`. Standard `datetime` only (no Pydantic-specific types).

**`JSONRepresentation`**
- `data: dict[str, Any]` — arbitrary parsed payload; no internal validation. Placeholder for EPIC-02.

**`ResolutionRequestRecord`**
- `identifier: EntityMentionIdentifier` — triad, unique key
- `entity_mention: EntityMention` — full payload as submitted
- `content_hash: str` — SHA-256 hex, validated: `pattern=r'^[0-9a-f]{64}$'`
- `received_at: datetime` — must be timezone-aware (field_validator)
- `json_representation: JSONRepresentation | None = None`

**`LookupState`**
- `source_id: str` — `min_length=1`, unique key
- `last_snapshot: datetime` — must be timezone-aware
- `updated_at: datetime` — must be timezone-aware; cross-field: `updated_at >= last_snapshot`

### Hasher Extension

Add to `src/ers/commons/adapters/hasher.py`:

```python
class SHA256ContentHasher(ContentHasher):
    """Fast, deterministic hasher for content deduplication. Not for passwords."""
    def hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()
    def verify(self, content: str, hash: str) -> bool:
        return self.hash(content) == hash
```

### Acceptance Criteria

1. `from ers.request_registry.domain.records import ResolutionRequestRecord, LookupState` works.
2. All models frozen: mutation raises `ValidationError`.
3. `content_hash` rejects non-64-char or non-hex strings.
4. Naive datetimes rejected on all datetime fields.
5. `LookupState` rejects `updated_at < last_snapshot`.
6. `SHA256ContentHasher().hash("")` == `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
7. All unit tests pass.

---

## Implementation Outcomes

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
- **Total: 35 new tests, all pass. Full unit suite: 276/276 pass.**

### Key Decisions

- `LookupRequestType` uses `StrEnum` (consistent with `ResolutionOutcome` in commons), not `str, Enum` as shown in the EPIC spec overview. The task spec (`task11.md`) is authoritative here and explicitly requires `StrEnum`.
- `SHA256ContentHasher` added as a new class in the existing `hasher.py` — no existing classes modified, blast radius is zero.
- `records.py` imports only from stdlib, erspec, and `ers.commons.domain.data_transfer_objects` — no import from services, adapters (other than the base class in commons.domain), or entrypoints.
- All fields decorated with `Field(..., description="...")` consistent with the REST API domain style.

### Deviations from Spec

None. Implementation follows the task spec exactly.

### Commits

- Committed and merged.