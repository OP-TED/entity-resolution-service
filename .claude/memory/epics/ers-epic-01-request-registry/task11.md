# Task 1.1 — Domain Models: Request Registry

**Files:**
- Create: `src/ers/request_registry/domain/records.py`
- Create: `src/ers/request_registry/__init__.py`, `src/ers/request_registry/domain/__init__.py`
- Extend: `src/ers/commons/adapters/hasher.py` — add `SHA256ContentHasher`

---

## Models (`records.py`)

All inherit `FrozenDTO`. Standard `datetime` only (no Pydantic-specific types).

### `JSONRepresentation`
- `data: dict[str, Any]` — arbitrary parsed payload; no internal validation. Placeholder for EPIC-02.

### `ResolutionRequestRecord`
- `identifier: EntityMentionIdentifier` — triad, unique key
- `entity_mention: EntityMention` — full payload as submitted
- `content_hash: str` — SHA-256 hex, validated: `pattern=r'^[0-9a-f]{64}$'`
- `received_at: datetime` — must be timezone-aware (field_validator)
- `json_representation: JSONRepresentation | None = None`

### `LookupState`
- `source_id: str` — `min_length=1`, unique key
- `last_snapshot: datetime` — must be timezone-aware
- `updated_at: datetime` — must be timezone-aware; cross-field: `updated_at >= last_snapshot`

No `LookupRequestRecord` or `LookupRequestType` — SINGLE lookups are stateless; only the bulk watermark (`LookupState`) needs persistence.

---

## Hasher extension

Add to `src/ers/commons/adapters/hasher.py`:

```python
class SHA256ContentHasher(ContentHasher):
    """Fast, deterministic hasher for content deduplication. Not for passwords."""
    def hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()
    def verify(self, content: str, hash: str) -> bool:
        return self.hash(content) == hash
```

Service layer injects `ContentHasher` via constructor (DIP). Domain records store `content_hash: str` only — no knowledge of how it was computed.

---

## Acceptance criteria

1. `from ers.request_registry.domain.records import ResolutionRequestRecord, LookupState` works.
2. All models frozen: mutation raises `ValidationError`.
3. `content_hash` rejects non-64-char or non-hex strings.
4. Naive datetimes rejected on all datetime fields.
5. `LookupState` rejects `updated_at < last_snapshot`.
6. `SHA256ContentHasher().hash("")` == `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
7. All unit tests pass.
