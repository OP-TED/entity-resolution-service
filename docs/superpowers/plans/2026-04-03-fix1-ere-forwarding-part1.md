# Fix1 ERE Forwarding — Part 1: Service Layer (Unit Tests + Implementation)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After each curation action (accept/assign/reject), publish an `EntityMentionResolutionRequest` to the `ere_requests` Redis queue via `EREPublishService`.

**Architecture:** Add `EREPublishService` as a fourth constructor parameter to `DecisionCurationService`. After the existing `UserActionService.record_*` call, fetch the entity mention from the repository and publish a re-evaluation request. `curation` (Tier 3) importing from `ere_contract_client` (Tier 1) is valid per `.importlinter`.

**Tech Stack:** Python 3.12, pytest-asyncio, `erspec.models.ere.EntityMentionResolutionRequest`, `ers.ere_contract_client.services.ere_publish_service.EREPublishService`

---

## ERE Message Semantics

| Action | ERE field set | value |
|--------|--------------|-------|
| `accept_decision` | `proposed_cluster_ids` | `[decision.current_placement.cluster_id]` |
| `assign_decision(cluster_id)` | `proposed_cluster_ids` | `[cluster_id]` |
| `reject_decision` | `excluded_cluster_ids` | `[c.cluster_id for c in decision.candidates]` |

Entity mention is fetched via `_entity_mention_repository.find_by_identifiers([decision.about_entity_mention])`. If not found: log warning and skip. If `EREPublishService.publish_request` raises: log warning and do **not** re-raise (best-effort, user action already recorded).

---

## File Map

| File | Change |
|------|--------|
| `tests/unit/curation/services/test_decision_curation_service.py` | Add `ere_publish_service` fixture; add `TestAcceptDecisionPublishesERE`, `TestAssignDecisionPublishesERE`, `TestRejectDecisionPublishesERE` |
| `src/ers/curation/services/decision_curation_service.py` | Add `EREPublishService` param; add `_publish_reevaluation` helper; call it after each action |

---

### Task 1: Write failing unit tests for ERE publishing

**Files:**
- Modify: `tests/unit/curation/services/test_decision_curation_service.py`

- [ ] **Step 1: Add `ere_publish_service` fixture and update `service` fixture**

Open `tests/unit/curation/services/test_decision_curation_service.py`. Add after line 40 (after the `user_action_service` fixture):

```python
@pytest.fixture
def ere_publish_service() -> MagicMock:
    return create_autospec(EREPublishService, instance=True)
```

Update the `service` fixture (currently lines 43–53) to:

```python
@pytest.fixture
def service(
    decision_repository: MagicMock,
    entity_mention_repository: MagicMock,
    user_action_service: MagicMock,
    ere_publish_service: MagicMock,
) -> DecisionCurationService:
    return DecisionCurationService(
        decision_repository=decision_repository,
        entity_mention_repository=entity_mention_repository,
        user_action_service=user_action_service,
        ere_publish_service=ere_publish_service,
    )
```

Add to the import block at the top:

```python
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from erspec.models.ere import EntityMentionResolutionRequest
```

- [ ] **Step 2: Add `TestAcceptDecisionPublishesERE` class**

Append at the end of the file:

```python
class TestAcceptDecisionPublishesERE:
    async def test_accept_publishes_proposed_cluster(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        user_action_service: MagicMock,
        ere_publish_service: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        entity_mention = EntityMentionFactory.build(
            identifiedBy=decision.about_entity_mention
        )
        decision_repository.find_by_id.return_value = decision
        entity_mention_repository.find_by_identifiers.return_value = [entity_mention]
        user_action_service.record_accept = AsyncMock()
        ere_publish_service.publish_request = AsyncMock()

        await service.accept_decision(decision.id, actor="curator")

        ere_publish_service.publish_request.assert_awaited_once()
        request: EntityMentionResolutionRequest = (
            ere_publish_service.publish_request.call_args[0][0]
        )
        assert request.entity_mention == entity_mention
        assert request.proposed_cluster_ids == [decision.current_placement.cluster_id]
        assert request.excluded_cluster_ids == []

    async def test_accept_skips_ere_when_mention_not_found(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        user_action_service: MagicMock,
        ere_publish_service: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        decision_repository.find_by_id.return_value = decision
        entity_mention_repository.find_by_identifiers.return_value = []
        user_action_service.record_accept = AsyncMock()
        ere_publish_service.publish_request = AsyncMock()

        await service.accept_decision(decision.id, actor="curator")

        ere_publish_service.publish_request.assert_not_awaited()

    async def test_accept_swallows_ere_publish_error(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        user_action_service: MagicMock,
        ere_publish_service: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        entity_mention = EntityMentionFactory.build(
            identifiedBy=decision.about_entity_mention
        )
        decision_repository.find_by_id.return_value = decision
        entity_mention_repository.find_by_identifiers.return_value = [entity_mention]
        user_action_service.record_accept = AsyncMock()
        ere_publish_service.publish_request = AsyncMock(
            side_effect=ConnectionError("Redis down")
        )

        # Must not raise
        await service.accept_decision(decision.id, actor="curator")
```

- [ ] **Step 3: Add `TestAssignDecisionPublishesERE` class**

```python
class TestAssignDecisionPublishesERE:
    async def test_assign_publishes_requested_cluster(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        user_action_service: MagicMock,
        ere_publish_service: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        target_cluster = decision.candidates[0].cluster_id
        entity_mention = EntityMentionFactory.build(
            identifiedBy=decision.about_entity_mention
        )
        decision_repository.find_by_id.return_value = decision
        entity_mention_repository.find_by_identifiers.return_value = [entity_mention]
        user_action_service.record_assign = AsyncMock()
        ere_publish_service.publish_request = AsyncMock()

        await service.assign_decision(decision.id, cluster_id=target_cluster, actor="curator")

        ere_publish_service.publish_request.assert_awaited_once()
        request: EntityMentionResolutionRequest = (
            ere_publish_service.publish_request.call_args[0][0]
        )
        assert request.entity_mention == entity_mention
        assert request.proposed_cluster_ids == [target_cluster]
        assert request.excluded_cluster_ids == []
```

- [ ] **Step 4: Add `TestRejectDecisionPublishesERE` class**

```python
class TestRejectDecisionPublishesERE:
    async def test_reject_publishes_all_candidates_as_exclusions(
        self,
        service: DecisionCurationService,
        decision_repository: MagicMock,
        entity_mention_repository: MagicMock,
        user_action_service: MagicMock,
        ere_publish_service: MagicMock,
    ) -> None:
        decision = DecisionFactory.build()
        entity_mention = EntityMentionFactory.build(
            identifiedBy=decision.about_entity_mention
        )
        decision_repository.find_by_id.return_value = decision
        entity_mention_repository.find_by_identifiers.return_value = [entity_mention]
        user_action_service.record_reject = AsyncMock()
        ere_publish_service.publish_request = AsyncMock()

        await service.reject_decision(decision.id, actor="curator")

        ere_publish_service.publish_request.assert_awaited_once()
        request: EntityMentionResolutionRequest = (
            ere_publish_service.publish_request.call_args[0][0]
        )
        expected_exclusions = [c.cluster_id for c in decision.candidates]
        assert request.entity_mention == entity_mention
        assert request.excluded_cluster_ids == expected_exclusions
        assert request.proposed_cluster_ids == []
```

- [ ] **Step 5: Run the new tests — confirm they all FAIL**

```bash
poetry run pytest tests/unit/curation/services/test_decision_curation_service.py \
    -k "PublishesERE" -v 2>&1 | tail -20
```

Expected: `TypeError` or `AttributeError` — `DecisionCurationService.__init__` does not yet accept `ere_publish_service`.

---

### Task 2: Implement ERE publishing in `DecisionCurationService`

**Files:**
- Modify: `src/ers/curation/services/decision_curation_service.py`

- [ ] **Step 1: Add imports**

At the top of `decision_curation_service.py`, add after the existing imports:

```python
import logging

from erspec.models.ere import EntityMentionResolutionRequest

from ers.ere_contract_client.services.ere_publish_service import EREPublishService
```

Also add `EntityMention` to the existing `erspec.models.core` import line:

```python
from erspec.models.core import Decision, EntityMention
```

(`EntityMention` is already imported via the `erspec.models.core` usage — verify and add if missing.)

Add at module level:

```python
log = logging.getLogger(__name__)
```

- [ ] **Step 2: Update `__init__` signature**

Replace the existing `__init__` (lines 30–38):

```python
    def __init__(
        self,
        decision_repository: DecisionRepository,
        entity_mention_repository: EntityMentionCurationRepository,
        user_action_service: UserActionService,
        ere_publish_service: EREPublishService,
    ) -> None:
        self._decision_repository = decision_repository
        self._entity_mention_repository = entity_mention_repository
        self._user_action_service = user_action_service
        self._ere_publish_service = ere_publish_service
```

- [ ] **Step 3: Add `_publish_reevaluation` helper (private)**

Add after the `_get_decision_or_raise` method:

```python
    async def _publish_reevaluation(
        self,
        decision: Decision,
        proposed_cluster_ids: list[str] | None = None,
        excluded_cluster_ids: list[str] | None = None,
    ) -> None:
        """Publish an ERE re-evaluation request after a curation action.

        Fetches the entity mention from the repository and publishes a
        re-evaluation request to ERE. Skips silently if the entity mention
        is not found. Swallows ERE publish errors so the curation action
        response is not affected.

        Args:
            decision: The curated decision (provides entity mention identifier).
            proposed_cluster_ids: Clusters to propose (resolveConsideringRecommendation).
            excluded_cluster_ids: Clusters to exclude (resolveWithExclusions).
        """
        mentions = await self._entity_mention_repository.find_by_identifiers(
            [decision.about_entity_mention]
        )
        if not mentions:
            log.warning(
                "Entity mention not found for ERE re-evaluation: decision=%s identifier=%s",
                decision.id,
                decision.about_entity_mention,
            )
            return

        request = EntityMentionResolutionRequest(
            entity_mention=mentions[0],
            ere_request_id="",
            proposed_cluster_ids=proposed_cluster_ids or [],
            excluded_cluster_ids=excluded_cluster_ids or [],
        )
        try:
            await self._ere_publish_service.publish_request(request)
        except Exception:
            log.exception(
                "Failed to publish ERE re-evaluation for decision %s", decision.id
            )
```

- [ ] **Step 4: Update `accept_decision`**

Replace the body of `accept_decision`:

```python
    async def accept_decision(self, decision_id: str, actor: str) -> None:
        """Accept the top candidate for a decision.

        After recording the user action, forwards a resolveConsideringRecommendation
        request to ERE for re-evaluation with the current placement as the proposed cluster.

        Raises:
            NotFoundError: If the decision does not exist.
            AlreadyCuratedError: If already curated on current version.
        """
        decision = await self._get_decision_or_raise(decision_id)
        await self._user_action_service.record_accept(actor=actor, decision=decision)
        await self._publish_reevaluation(
            decision,
            proposed_cluster_ids=[decision.current_placement.cluster_id],
        )
```

- [ ] **Step 5: Update `reject_decision`**

```python
    async def reject_decision(self, decision_id: str, actor: str) -> None:
        """Reject all candidates for a decision.

        After recording the user action, forwards a resolveWithExclusions
        request to ERE for re-evaluation excluding all current candidates.

        Raises:
            NotFoundError: If the decision does not exist.
            AlreadyCuratedError: If already curated on current version.
        """
        decision = await self._get_decision_or_raise(decision_id)
        await self._user_action_service.record_reject(actor=actor, decision=decision)
        await self._publish_reevaluation(
            decision,
            excluded_cluster_ids=[c.cluster_id for c in decision.candidates],
        )
```

- [ ] **Step 6: Update `assign_decision`**

```python
    async def assign_decision(self, decision_id: str, cluster_id: str, actor: str) -> None:
        """Assign a decision to an alternative cluster.

        After recording the user action, forwards a resolveConsideringRecommendation
        request to ERE for re-evaluation with the assigned cluster as the proposed cluster.

        Raises:
            NotFoundError: If the decision does not exist.
            AlreadyCuratedError: If already curated on current version.
            InvalidClusterError: If cluster_id is not in candidates.
        """
        decision = await self._get_decision_or_raise(decision_id)
        await self._user_action_service.record_assign(
            actor=actor, decision=decision, cluster_id=cluster_id
        )
        await self._publish_reevaluation(
            decision,
            proposed_cluster_ids=[cluster_id],
        )
```

- [ ] **Step 7: Run unit tests — confirm new tests pass**

```bash
poetry run pytest tests/unit/curation/services/test_decision_curation_service.py -v 2>&1 | tail -30
```

Expected: All tests in `TestAcceptDecisionPublishesERE`, `TestAssignDecisionPublishesERE`, `TestRejectDecisionPublishesERE` **PASS**. Existing tests **FAIL** if not yet updated (fixture lacks `ere_publish_service`).

- [ ] **Step 8: Commit**

```bash
git add src/ers/curation/services/decision_curation_service.py \
        tests/unit/curation/services/test_decision_curation_service.py
git commit -m "feat(curation): publish ERE re-evaluation request after each curation action"
```
