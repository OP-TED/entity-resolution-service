# Fix1 ERE Forwarding — Part 2: Fix Broken Dependent Tests + Fixtures

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all d=1 callers of `DecisionCurationService.__init__` that break after adding the `ere_publish_service` parameter in Part 1. Four sites need updating.

**Architecture:** No logic changes — only fixture/factory updates to supply the new `ere_publish_service` mock or real instance.

**Tech Stack:** pytest, `create_autospec`, `EREPublishService`

---

## File Map

| File | Change |
|------|--------|
| `tests/unit/curation/services/test_decision_curation_service.py` | `service` fixture already updated in Part 1 — verify |
| `tests/feature/link_curation_api/conftest.py` | Add `ere_publish_service` fixture; pass to `DecisionCurationService` |
| `tests/unit/curation/api/test_dependencies.py` | Update `test_get_decision_curation_service` to pass `ere_publish_service` mock |

---

### Task 3: Fix feature-test conftest

**Files:**
- Modify: `tests/feature/link_curation_api/conftest.py`

- [ ] **Step 1: Read current state**

```bash
poetry run pytest tests/feature/link_curation_api/ --collect-only 2>&1 | tail -10
```

Expected: collection errors because `DecisionCurationService.__init__` now requires `ere_publish_service`.

- [ ] **Step 2: Add import and `ere_publish_service` fixture**

In `tests/feature/link_curation_api/conftest.py`, add to the import block:

```python
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
```

After the `password_hasher` fixture (around line 122), add:

```python
@pytest.fixture
def ere_publish_service() -> AsyncMock:
    mock = create_autospec(EREPublishService, instance=True)
    mock.publish_request = AsyncMock()
    return mock
```

- [ ] **Step 3: Update `decision_curation_service` fixture**

Replace the existing fixture (lines ~147–157):

```python
@pytest.fixture
def decision_curation_service(
    decision_repository: AsyncMock,
    entity_mention_repository: AsyncMock,
    user_action_service: UserActionService,
    ere_publish_service: AsyncMock,
) -> DecisionCurationService:
    return DecisionCurationService(
        decision_repository=decision_repository,
        entity_mention_repository=entity_mention_repository,
        user_action_service=user_action_service,
        ere_publish_service=ere_publish_service,
    )
```

- [ ] **Step 4: Run feature tests — confirm they collect and pass**

```bash
poetry run pytest tests/feature/link_curation_api/ -v 2>&1 | tail -20
```

Expected: All feature tests **PASS** (ERE publish is mocked and never asserted in these tests).

---

### Task 4: Fix unit test for dependency provider

**Files:**
- Modify: `tests/unit/curation/api/test_dependencies.py`

- [ ] **Step 1: Read the test**

Open `tests/unit/curation/api/test_dependencies.py`, find `test_get_decision_curation_service` (around line 97–104):

```python
    async def test_get_decision_curation_service(self):
        mock_decision_repo = MagicMock()
        mock_entity_repo = MagicMock()
        mock_user_action_service = MagicMock()
        result = await get_decision_curation_service(
            mock_decision_repo, mock_entity_repo, mock_user_action_service
        )
        assert isinstance(result, DecisionCurationService)
```

This will fail because `get_decision_curation_service` (after Part 3 changes) will require an `EREPublishService` argument.

- [ ] **Step 2: Update the test**

Add import if not already present:

```python
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
```

Replace the test body:

```python
    async def test_get_decision_curation_service(self):
        mock_decision_repo = MagicMock()
        mock_entity_repo = MagicMock()
        mock_user_action_service = MagicMock()
        mock_ere_publish_service = create_autospec(EREPublishService, instance=True)
        result = await get_decision_curation_service(
            mock_decision_repo,
            mock_entity_repo,
            mock_user_action_service,
            mock_ere_publish_service,
        )
        assert isinstance(result, DecisionCurationService)
```

Note: This test will pass only **after** Part 3 updates `get_decision_curation_service` to accept and forward `ere_publish_service`. Run it in verification after Part 3.

- [ ] **Step 3: Run all unit curation tests**

```bash
poetry run pytest tests/unit/curation/ -v 2>&1 | tail -30
```

Expected: All existing tests pass. `test_get_decision_curation_service` may still fail until Part 3 is applied.

- [ ] **Step 4: Commit**

```bash
git add tests/feature/link_curation_api/conftest.py \
        tests/unit/curation/api/test_dependencies.py
git commit -m "fix(tests): supply ere_publish_service mock in curation fixtures after signature change"
```