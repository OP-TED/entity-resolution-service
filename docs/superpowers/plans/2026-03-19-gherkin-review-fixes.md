# Gherkin Review Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address PR review feedback: fix terminology, move `ResolutionOutcome` to commons, add SINGLE lookup scenarios, remove empty-content scenario, update EPIC-01 spec.

**Architecture:** Four independent changes to feature files, step definitions, domain models, and EPIC spec. No new layers or components — all edits to existing files.

**Tech Stack:** Pydantic models, pytest-bdd/Gherkin, erspec

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/ers/commons/domain/data_transfer_objects.py` | Modify | Add `ResolutionOutcome` enum |
| `src/ers/ers_rest_api/domain/resolution.py` | Modify | Import `ResolutionOutcome` from commons instead of defining it |
| `tests/feature/request_registry/bulk_lookup_and_snapshot_management.feature` | Modify | Rename title, add 2 SINGLE lookup scenarios |
| `tests/feature/request_registry/test_bulk_lookup_and_snapshot_management.py` | Modify | Add scenario bindings + step defs for SINGLE lookup |
| `tests/feature/request_registry/resolution_request_registration.feature` | Modify | Remove empty-content scenario, add rejection scenario |
| `tests/feature/request_registry/test_resolution_request_registration.py` | Modify | Remove empty-content binding + step defs, add rejection binding + step defs |
| `.claude/memory/epics/ers-epic-01-request-registry/EPIC.md` | Modify | `WatermarkRegressionError` → `SnapshotRegressionError` |

---

### Task 1: Fix exception naming in EPIC-01 spec

Standardise on `SnapshotRegressionError` (matches `LookupState.last_snapshot` field and existing Gherkin).

**Files:**
- Modify: `.claude/memory/epics/ers-epic-01-request-registry/EPIC.md`
- Modify: `tests/feature/request_registry/test_bulk_lookup_and_snapshot_management.py`

- [ ] **Step 1: Update EPIC-01 spec — rename exception**

In `.claude/memory/epics/ers-epic-01-request-registry/EPIC.md`:

1. Replace **all** occurrences of `WatermarkRegressionError` with `SnapshotRegressionError` (5 occurrences: lines 297, 305, 360, 387, 452).
2. Replace **all** occurrences of `advance_lookup_watermark` with `advance_snapshot` (7 occurrences: lines 289, 297, 359, 360, 450, 451, 452) to align with the Gherkin wording ("the snapshot is advanced to").

Use find-and-replace for both — do not enumerate manually.

- [ ] **Step 2: Fix step def docstring inconsistency**

In `tests/feature/request_registry/test_bulk_lookup_and_snapshot_management.py`, line 9 says `WatermarkRegressionError` in the module docstring. Update it to `SnapshotRegressionError`.

- [ ] **Step 3: Verify no other references to old name**

Run: `grep -r "WatermarkRegressionError" --include="*.py" --include="*.feature" --include="*.md" .`

Expected: zero matches.

- [ ] **Step 4: Run existing tests to confirm no breakage**

Run: `make test` or `pytest tests/feature/request_registry/ -v`

Expected: all existing tests still pass (they use TODO stubs, so no functional change).

---

### Task 2: Move `ResolutionOutcome` to commons

`ResolutionOutcome` (CANONICAL/PROVISIONAL) is a domain concept shared across EPIC-07 (REST API response) and will be needed by EPIC-06 (Resolution Coordinator). Move it to `ers.commons.domain`.

**Files:**
- Modify: `src/ers/commons/domain/data_transfer_objects.py`
- Modify: `src/ers/ers_rest_api/domain/resolution.py`

- [ ] **Step 1: Add `ResolutionOutcome` to commons**

In `src/ers/commons/domain/data_transfer_objects.py`, add after the existing imports:

```python
from enum import StrEnum
```

Then add the enum after the `PaginatedResult` class:

```python
class ResolutionOutcome(StrEnum):
    """Possible outcomes of a single entity mention resolution.

    CANONICAL — the cluster ID was produced by the Entity Resolution Engine.
    PROVISIONAL — the cluster ID was derived deterministically (singleton).
    """

    CANONICAL = "CANONICAL"
    PROVISIONAL = "PROVISIONAL"
```

- [ ] **Step 2: Update `resolution.py` to import from commons**

In `src/ers/ers_rest_api/domain/resolution.py`:
- Remove the `from enum import StrEnum` import
- Remove the `ResolutionOutcome` class definition (lines 14-18)
- Add to the commons import line:

```python
from ers.commons.domain.data_transfer_objects import ERSRequest, ERSResponse, ResolutionOutcome
```

- [ ] **Step 3: Verify imports resolve correctly**

Run: `python -c "from ers.commons.domain.data_transfer_objects import ResolutionOutcome; print(ResolutionOutcome.CANONICAL)"`

Expected: `CANONICAL`

Run: `python -c "from ers.ers_rest_api.domain.resolution import ResolutionOutcome; print(ResolutionOutcome.PROVISIONAL)"`

Expected: `PROVISIONAL`

Note: `data_transfer_objects.py` (legacy) keeps its own `ResolutionOutcome` definition — it will be removed when that file is retired. Do not touch it.

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -v --tb=short -q`

Expected: all pass, no import errors.

---

### Task 3: Add SINGLE lookup scenarios to feature file

Add two scenarios covering `LookupRequestRecord(request_type=SINGLE)` and broaden the feature title.

**Files:**
- Modify: `tests/feature/request_registry/bulk_lookup_and_snapshot_management.feature`
- Modify: `tests/feature/request_registry/test_bulk_lookup_and_snapshot_management.py`

- [ ] **Step 1: Update feature file — rename title and add scenarios**

In `tests/feature/request_registry/bulk_lookup_and_snapshot_management.feature`:

Replace the title block (lines 1-5) with:

```gherkin
Feature: Lookup Request Registration and Snapshot State Management
  As a process that coordinates entity mention lookups and delta exposure for source systems,
  I want to register both single and bulk lookup requests and advance the snapshot watermark per source,
  So that each source's lookup activity is tracked for audit
  and each source's last successful bulk refresh point is tracked reliably
  and backward time movement is detected and rejected.
```

After the "Register multiple bulk lookup requests from the same source" scenario (after line 33), insert:

```gherkin

  Scenario Outline: Register a single lookup request
    Given a source system identified by "<source_id>"
    When a single lookup request is registered for "<source_id>"
    Then a lookup request record is returned for "<source_id>"
    And the lookup request record has request type SINGLE
    And the lookup request record has a requested_at timestamp set to the current UTC time

    Examples:
      | source_id       |
      | source_system_a |
      | source_system_b |

  Scenario Outline: Register lookup requests of different types from the same source
    Given a source system identified by "<source_id>"
    And a bulk lookup request has already been registered for "<source_id>"
    When a single lookup request is registered for "<source_id>"
    Then both lookup request records exist in the repository for "<source_id>"
    And the earlier record is not modified

    Examples:
      | source_id       |
      | source_system_a |
      | source_system_b |
```

- [ ] **Step 2: Add scenario bindings to step definitions**

In `tests/feature/request_registry/test_bulk_lookup_and_snapshot_management.py`, add after the `test_register_multiple_bulk_lookups` binding (after line 43):

```python
@scenario(FEATURE_FILE, "Register a single lookup request")
def test_register_single_lookup_request():
    """Bind the 'Register a single lookup request' scenario outline."""
    pass


@scenario(FEATURE_FILE, "Register lookup requests of different types from the same source")
def test_register_mixed_lookup_types():
    """Bind the 'Register lookup requests of different types' scenario outline."""
    pass
```

- [ ] **Step 3: Add SINGLE When step definition**

In the same file, in the "When" section (after line 246), add:

```python
@when(parsers.parse('a single lookup request is registered for "{source_id}"'))
def register_single_lookup_request(ctx, source_id):
    """
    Call RequestRegistryService.register_lookup_request with SINGLE type.

    Captures the returned LookupRequestRecord or any raised exception.

    TODO: Replace with real async call:
        import asyncio
        from ers.request_registry.domain.records import LookupRequestType
        ctx["result"] = asyncio.run(
            ctx["service"].register_lookup_request(source_id, LookupRequestType.SINGLE)
        )
    """
    returned_record = MagicMock()
    returned_record.source_id = source_id
    returned_record.requested_at = datetime.now(UTC)
    # TODO: returned_record.request_type = LookupRequestType.SINGLE
    ctx["repository"].store_lookup_request = AsyncMock(return_value=returned_record)
    ctx["result"] = returned_record  # TODO: replace with real service call
    ctx["raised_exception"] = None
    # If a prior bulk record exists, update find to return both (mixed-types scenario)
    existing = ctx.get("existing_lookup_record")
    if existing is not None:
        ctx["repository"].find_lookup_requests_by_source = AsyncMock(
            return_value=[existing, returned_record]
        )
```

- [ ] **Step 4: Add SINGLE Then step definition**

In the "Then" section, add:

```python
@then("the lookup request record has request type SINGLE")
def lookup_record_has_single_type(ctx):
    """
    Assert that the returned LookupRequestRecord.request_type is LookupRequestType.SINGLE.

    TODO: from ers.request_registry.domain.records import LookupRequestType
          assert ctx["result"].request_type == LookupRequestType.SINGLE
    """
    assert True  # TODO: implement
```

- [ ] **Step 5: Update module docstring**

Update the docstring at the top of the file (lines 1-11) to reflect the broader scope:

```python
"""
Step definitions for: bulk_lookup_and_snapshot_management.feature

Feature: Lookup Request Registration and Snapshot State Management
  Covers seven behaviours:
    1. Registering a bulk lookup request creates an append-only LookupRequestRecord.
    2. Multiple bulk lookups from the same source accumulate without overwriting.
    3. Registering a single lookup request creates an append-only LookupRequestRecord.
    4. Single and bulk lookup records from the same source coexist independently.
    5. Advancing the snapshot watermark for a known source updates LookupState.last_snapshot.
    6. Advancing the snapshot to the current or earlier time raises SnapshotRegressionError.
    7. Retrieving lookup state for known/unknown sources returns the correct result.

  These steps call RequestRegistryService with a mocked or in-memory repository.
  No real MongoDB connection is required for unit-level BDD scenarios.
"""
```

- [ ] **Step 6: Run feature tests**

Run: `pytest tests/feature/request_registry/test_bulk_lookup_and_snapshot_management.py -v`

Expected: all 10 scenarios pass (6 existing from outlines + 4 new from outlines).

---

### Task 4: Remove empty-content scenario, add rejection scenario

Empty content is now a validation error (rejected at both API and service layer). Replace the "accepts empty content" scenario with a "rejects empty content" scenario.

**Files:**
- Modify: `tests/feature/request_registry/resolution_request_registration.feature`
- Modify: `tests/feature/request_registry/test_resolution_request_registration.py`

- [ ] **Step 1: Replace empty-content scenario in feature file**

In `tests/feature/request_registry/resolution_request_registration.feature`, replace lines 24-29:

```gherkin
  Scenario: Register a resolution request with empty content
    Given an entity mention with source_id "source_system_a", request_id "req_003", entity_type "person", and empty content
    When the resolution request is registered
    Then a resolution request record is returned
    And the record content_hash is the SHA-256 digest of the empty string
    And the record received_at timestamp is set to the current UTC time
```

With:

```gherkin
  Scenario: Reject a resolution request with empty content
    Given an entity mention with source_id "source_system_a", request_id "req_003", entity_type "person", and empty content
    When the resolution request is registered
    Then a validation error is raised indicating content must not be empty
    And no record is created in the repository
```

- [ ] **Step 2: Update scenario binding in step definitions**

In `tests/feature/request_registry/test_resolution_request_registration.py`, replace lines 54-57:

```python
@scenario(FEATURE_FILE, "Register a resolution request with empty content")
def test_register_resolution_request_with_empty_content():
    """Bind the 'Register a resolution request with empty content' scenario."""
    pass
```

With:

```python
@scenario(FEATURE_FILE, "Reject a resolution request with empty content")
def test_reject_resolution_request_with_empty_content():
    """Bind the 'Reject a resolution request with empty content' scenario."""
    pass
```

- [ ] **Step 3: Add new Then step definitions for rejection**

In the "Then" section of the same file, add:

```python
@then("a validation error is raised indicating content must not be empty")
def validation_error_for_empty_content(ctx):
    """
    Assert that the service raised a validation error when content is empty.

    TODO: from ers.request_registry.services.exceptions import ValidationError
          assert isinstance(ctx["raised_exception"], ValidationError)
          assert "content" in str(ctx["raised_exception"]).lower()
    """
    assert ctx["raised_exception"] is not None
    assert True  # TODO: assert isinstance(ctx["raised_exception"], ValidationError)


@then("no record is created in the repository")
def no_record_created(ctx):
    """
    Assert that store_resolution_request was NOT called.

    TODO: ctx["repository"].store_resolution_request.assert_not_called()
    """
    assert True  # TODO: implement
```

- [ ] **Step 4: Update the When step for empty content to simulate rejection**

The existing `register_resolution_request` When step (line 211) currently sets `ctx["result"] = None`. For the empty content scenario, we need it to capture a validation error. Update the step to detect empty content:

In the `register_resolution_request` function body, replace:

```python
    ctx["result"] = None  # TODO: replace with real async service call
    ctx["raised_exception"] = None
```

With:

```python
    # TODO: Replace the stub with a real async call:
    #     import asyncio
    #     try:
    #         ctx["result"] = asyncio.run(
    #             ctx["service"].register_resolution_request(ctx["entity_mention"])
    #         )
    #         ctx["raised_exception"] = None
    #     except Exception as exc:
    #         ctx["result"] = None
    #         ctx["raised_exception"] = exc
    content = ctx.get("content", "")
    if content == "":
        ctx["result"] = None
        ctx["raised_exception"] = Exception("ValidationError: content must not be empty")  # placeholder
    else:
        ctx["result"] = None  # TODO: replace with real service call
        ctx["raised_exception"] = None
```

- [ ] **Step 5: Remove the orphaned empty-string hash step**

Remove the `record_content_hash_is_sha256_of_empty_string` function (lines 322-332) — it's no longer referenced by any scenario.

- [ ] **Step 6: Update the `an_entity_mention_with_empty_content` step docstring**

Update the docstring of `an_entity_mention_with_empty_content` (line 168) to reflect the new intent:

```python
def an_entity_mention_with_empty_content(ctx, source_id, request_id, entity_type):
    """
    Build an EntityMention with empty string content.

    Used by the rejection scenario — the service must reject empty content
    with a validation error.
    """
    an_entity_mention(ctx, source_id, request_id, entity_type, "")
```

- [ ] **Step 7: Update module docstring**

Update the module docstring (lines 1-13) to reflect the change:

```python
"""
Step definitions for: resolution_request_registration.feature

Feature: Resolution Request Registration
  Covers four behaviours:
    1. Registering a new entity mention produces a ResolutionRequestRecord with the
       correct triad, content_hash (SHA-256), and received_at timestamp.
    2. Replaying an identical triad+content returns the existing record (idempotent).
    3. Replaying the same triad with different content raises IdempotencyConflictError.
    4. Submitting empty content is rejected with a validation error.

  These steps call the RequestRegistryService with a mocked or in-memory repository.
  No real MongoDB connection is required for unit-level BDD scenarios.
"""
```

- [ ] **Step 8: Run feature tests**

Run: `pytest tests/feature/request_registry/test_resolution_request_registration.py -v`

Expected: all 5 scenarios pass (2 from outline + 3 individual).

---

### Task 5: Final verification

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short -q`

Expected: all tests pass, no import errors, no broken references.

- [ ] **Step 2: Verify terminology consistency**

Run: `grep -r "WatermarkRegressionError" --include="*.py" --include="*.feature" --include="*.md" .`

Expected: zero matches.

Run: `grep -r "empty content" tests/feature/request_registry/resolution_request_registration.feature`

Expected: only the rejection scenario line.

- [ ] **Step 3: Commit**

Stage and commit all changes as a single atomic commit — all four changes address the same PR review feedback.

```bash
git add src/ers/commons/domain/data_transfer_objects.py \
        src/ers/ers_rest_api/domain/resolution.py \
        tests/feature/request_registry/ \
        .claude/memory/epics/ers-epic-01-request-registry/EPIC.md
git commit -m "fix(gherkin): address PR review — terminology, ResolutionOutcome to commons, SINGLE lookup, empty content rejection"
```
