# Task 7X: Wire E2E Step Definitions (post-implementation)

## Context

After EPIC-07 implementation is complete, three e2e scaffold files need wiring with
real HTTP calls against the FastAPI app. These are the top-level black-box tests -
they test the full stack through the HTTP boundary.

Do not attempt this before the FastAPI app, `ResolutionCoordinatorService` (EPIC-06),
and `OutcomeIntegrationWorker` (EPIC-05) are all wired in the lifespan.

---

## Prerequisite

- EPIC-05, EPIC-06, and EPIC-07 implementation complete
- FastAPI lifespan wires: `OutcomeIntegrationWorker.start()`, coordinator, decision store
- All feature-level and integration tests passing

---

## Files to Update

| Path | What changes |
|------|-------------|
| `tests/e2e/ucs/test_ucb11_resolve_entity_mention.py` | Replace coordinator-level TODOs with HTTP calls via FastAPI `TestClient` |
| `tests/e2e/ucs/test_e2e_resolution_cycle.py` | Full black-box cycle: POST /resolve → ERE mock → GET /lookup |
| `tests/e2e/ucs/test_ucb21_submit_user_reevaluation.py` | UC-B2.1 - requires curation API (may be later EPIC) |
| `tests/e2e/ucs/test_ucb22_bulk_curator_reevaluation.py` | UC-B2.2 - requires curation API (may be later EPIC) |
| `tests/e2e/ucs/test_ucw4_consult_resolution_statistics.py` | UC-W4 - stats endpoint (may be later EPIC) |

## Priority Order & Status

1. ✅ **`test_ucb11_resolve_entity_mention.py`** — 19 scenarios wired (2026-04-01, task 6X)
2. ⏸️ **`test_e2e_resolution_cycle.py`** — deferred (cross-endpoint state coordination); feature file updated, skip marker added
3. ⏸️ `test_ucb21`, `test_ucb22`, `test_ucw4` — blocked on future EPICs; skip markers added

---

## Pattern to Follow

Use FastAPI `TestClient` or `httpx.AsyncClient` with `app` from the lifespan:

```python
from fastapi.testclient import TestClient
from ers.ers_rest_api.entrypoints.app import create_app  # or however the app factory is named

@pytest.fixture
def client():
    app = create_app(...)
    with TestClient(app) as c:
        yield c
```

For scenarios involving async ERE responses (Spine B), use a mock Redis or an
`AsyncOutcomeListener` fake that yields pre-configured responses.

---

## Scenarios by File

### `test_ucb11_resolve_entity_mention.py` (10 scenarios)
- POST /resolve with valid mention -> canonical cluster ID
- POST /resolve with ERE timeout -> provisional singleton ID
- POST /resolve idempotent replay -> same cluster ID returned
- POST /resolve idempotency conflict -> 409 or 400
- POST /resolve validation errors -> 400
- POST /resolve ERE unavailable -> provisional or error response
- POST /bulk-resolve with multiple mentions -> list of results

### `test_e2e_resolution_cycle.py` (4 scenarios)
- Full cycle: resolve -> ERE mock outcome -> lookup returns canonical ID
- Provisional -> canonical transition after ERE responds
- Idempotent replay cycle
- Multiple mentions batch cycle

---

## Note on UC-B1.1 vs UC-B1.2 e2e overlap

`test_ucb11_resolve_entity_mention.py` overlaps with `test_ucb12_integrate_ere_outcomes.py`
(EPIC-05 task 58) for the async outcome side. The split is:
- UC-B1.1 e2e: tests the *resolve request intake* side (HTTP in, provisional out, then canonical)
- UC-B1.2 e2e: tests the *outcome consumption* side (ERE message in, Decision Store updated)
- `test_e2e_resolution_cycle.py`: tests both sides together end-to-end

---

## Key References

| What | Where |
|------|-------|
| EPIC-07 spec | `.claude/memory/epics/ers-epic-07-ere-rest-api/EPIC.md` |
| Gherkin specs | `tests/e2e/ucs/ucb11_resolve_entity_mention.feature`, `e2e_resolution_cycle.feature` |
| FastAPI app wiring | `.claude/memory/epics/ers-epic-07-ere-rest-api/coordination-work.md` |
| EPIC-05 e2e task | `.claude/memory/epics/ers-epic-05-ere-result-integrator/task58-e2e-ucb12-wiring.md` |
| EPIC-06 e2e task | `.claude/memory/epics/ers-epic-06-resolution-coordinator/task6x-e2e-ucb11-wiring.md` |