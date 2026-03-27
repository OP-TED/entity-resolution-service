# Task 8: Wire E2E Step Definitions for UC-B1.2

## Context

EPIC-05 implementation is complete (tasks 51-57). The e2e test file for UC-B1.2 was
created as a scaffold before implementation existed. Now that `OutcomeIntegrationService`
is implemented and tested, the TODO placeholders can be replaced with real service calls.

The feature-level BDD tests (`tests/feature/ere_result_integrator/`) already demonstrate
the exact pattern to follow. This task is essentially porting that pattern to the e2e layer.

---

## Files to Update

| Path | What changes |
|------|-------------|
| `tests/e2e/ucs/test_ucb12_integrate_ere_outcomes.py` | Replace all TODO placeholders with real `OutcomeIntegrationService` calls |

## Files to Review (not modify)

| Path | Why |
|------|-----|
| `tests/e2e/ucs/ucb12_integrate_ere_outcomes.feature` | Contains one misplaced scenario - see Note below |
| `tests/feature/ere_result_integrator/test_outcome_acceptance.py` | Reference implementation to follow |
| `tests/feature/ere_result_integrator/test_contract_validation.py` | Reference implementation to follow |

---

## Step 1 - Wire the Background / ctx Fixture

Replace the `ers_system_operational` step and add a proper `ctx` fixture:

```python
from datetime import UTC, datetime
from unittest.mock import AsyncMock, create_autospec

from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier
from erspec.models.ere import EntityMentionResolutionResponse

from ers.ere_result_integrator.domain.errors import OutcomeValidationError, TriadNotFoundError
from ers.ere_result_integrator.services.outcome_integration_service import OutcomeIntegrationService
from ers.request_registry.domain.records import ResolutionRequestRecord
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_decision_store.domain.errors import StaleOutcomeError
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService


@pytest.fixture
def _loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def ctx(_loop):
    registry = create_autospec(RequestRegistryService, instance=True)
    decisions = create_autospec(DecisionStoreService, instance=True)
    service = OutcomeIntegrationService(
        registry_service=registry,
        decision_service=decisions,
        on_outcome_stored=None,
    )
    return {
        "loop": _loop,
        "registry": registry,
        "decisions": decisions,
        "service": service,
        "source_id": None,
        "request_id": None,
        "entity_type": None,
        "outcome_cluster_id": None,
        "outcome_alt_count": 0,
        "result": None,
        "raised_exception": None,
    }
```

---

## Step 2 - Wire Given Steps

### `mention_is_registered`
```python
from ers.commons.adapters.hasher import SHA256ContentHasher

ctx["registry"].get_resolution_request = AsyncMock(
    return_value=ResolutionRequestRecord(
        identifiedBy=EntityMentionIdentifier(
            source_id=source_id, request_id=request_id, entity_type=entity_type
        ),
        content="rdf",
        content_type="text/turtle",
        content_hash="a" * 64,
        received_at=datetime.now(UTC),
    )
)
```

### `mention_not_registered`
```python
ctx["registry"].get_resolution_request = AsyncMock(return_value=None)
```

### `decision_store_holds_cluster`
```python
# Seed the mock decision store with a prior cluster (will be replaced by new outcome)
ctx["prior_cluster_id"] = cluster_id
```

### `ere_emits_outcome` / `ere_emits_outcome_short`
Build `ctx["outcome_message"]` as an `EntityMentionResolutionResponse`:
```python
primary = ClusterReference(cluster_id=cluster_id, confidence_score=0.95, similarity_score=0.90)
alts = [
    ClusterReference(cluster_id=f"alt-{i}", confidence_score=0.5, similarity_score=0.45)
    for i in range(alt_count)
]
identifier = EntityMentionIdentifier(
    source_id=ctx["source_id"],
    request_id=ctx["request_id"],
    entity_type=ctx["entity_type"],
)
ctx["outcome_message"] = EntityMentionResolutionResponse(
    ere_request_id=f"{ctx['request_id']}:001",
    entity_mention_id=identifier,
    candidates=[primary] + alts,
    timestamp=datetime.now(UTC),
)
# Wire the decision store mock to return a matching Decision
now = datetime.now(UTC)
ctx["decisions"].store_decision = AsyncMock(return_value=Decision(
    id="hash",
    about_entity_mention=identifier,
    current_placement=primary,
    candidates=alts,
    created_at=now,
    updated_at=now,
))
```

---

## Step 3 - Wire When Steps

### `consume_outcome`
```python
try:
    ctx["result"] = ctx["loop"].run_until_complete(
        ctx["service"].integrate_outcome(ctx["outcome_message"])
    )
    ctx["raised_exception"] = None
except (OutcomeValidationError, TriadNotFoundError, Exception) as exc:
    ctx["result"] = None
    ctx["raised_exception"] = exc
```

### `consume_duplicate_outcome`
Call `integrate_outcome` again with the same message. Configure `store_decision` to raise
`StaleOutcomeError` on the second call (same timestamp = stale):
```python
ctx["decisions"].store_decision = AsyncMock(
    side_effect=StaleOutcomeError(
        ctx["source_id"], ctx["request_id"], ctx["entity_type"],
        stored_at="T1", attempted_at="T1"
    )
)
# call service again - must not raise
ctx["loop"].run_until_complete(
    ctx["service"].integrate_outcome(ctx["outcome_message"])
)
```

---

## Step 4 - Wire Then Steps

### `decision_store_reflects_cluster`
```python
assert ctx["raised_exception"] is None
ctx["decisions"].store_decision.assert_called()
call_kwargs = ctx["decisions"].store_decision.call_args.kwargs
assert call_kwargs["current"].cluster_id == cluster_id
```

### `decision_has_n_alternatives`
```python
call_kwargs = ctx["decisions"].store_decision.call_args.kwargs
assert len(call_kwargs["candidates"]) == count
```

### `scores_preserved` / `scores_match_table`
```python
call_kwargs = ctx["decisions"].store_decision.call_args.kwargs
for i, expected in enumerate(ctx["outcome_alternatives"]):
    assert call_kwargs["candidates"][i].cluster_id == expected["cluster_id"]
    assert call_kwargs["candidates"][i].confidence_score == expected["confidence"]
    assert call_kwargs["candidates"][i].similarity_score == expected["similarity"]
```

### `no_decision_written`
```python
ctx["decisions"].store_decision.assert_not_called()
```

### `outcome_rejected`
```python
assert ctx["raised_exception"] is not None
```

### `delta_tracking_updated`
```python
call_kwargs = ctx["decisions"].store_decision.call_args.kwargs
assert call_kwargs["updated_at"] is not None
```

---

## Note: Misplaced Scenario

The scenario **"Messaging publish failure does not modify Decision Store state"**
(feature file line 118-124) tests the *outbound publish* path to ERE.
`OutcomeIntegrationService` is a consumer and has no publisher, so this scenario
cannot be driven through it. Options:
- Remove the scenario from this feature file (it is already covered by ERE Contract Client tests)
- Move it to `ucb11_resolve_entity_mention.feature` where publish failures are in scope

Discuss with developer before changing the `.feature` file.

---

## Step 5 - Verify

```bash
poetry run pytest tests/e2e/ucs/test_ucb12_integrate_ere_outcomes.py -v -m e2e
```

All scenarios must pass (or xfail the misplaced messaging scenario pending discussion).

---

## Key References

| What | Where |
|------|-------|
| Reference implementation | `tests/feature/ere_result_integrator/test_outcome_acceptance.py` |
| Reference implementation | `tests/feature/ere_result_integrator/test_contract_validation.py` |
| `OutcomeIntegrationService` | `src/ers/ere_result_integrator/services/outcome_integration_service.py` |
| E2E Gherkin spec | `tests/e2e/ucs/ucb12_integrate_ere_outcomes.feature` |
