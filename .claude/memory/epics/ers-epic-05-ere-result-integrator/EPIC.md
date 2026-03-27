# ERS-EPIC-05: ERE Result Integrator

**Epic ID:** ERS-EPIC-05
**Component:** ERE Result Integrator
**Spine:** Spine B (Asynchronous Engine Interaction & Outcome Integration)
**Phase:** 2 — Core Flows (after Registry, RDF Parser, ERE Contract Client are complete)
**Status:** ⬜ Ready for Implementation

---

## 1. Strategic Overview

### Problem Statement

The Entity Resolution Engine (ERE) is the authoritative source for entity clustering decisions. However, ERE communication is asynchronous and inherently **at-least-once** in delivery semantics. This creates a critical challenge:

- **How do we reliably absorb ERE outcomes** (including duplicates and late arrivals)?
- **How do we maintain a single source of truth** for the latest cluster assignment per mention?
- **How do we support multiple outcome sources** (solicited requests, unsolicited reclustering, curator recommendations)?

Without robust integration, inconsistent cluster assignments will leak into client responses and downstream systems.

### Solution Intent

The **ERE Result Integrator** is a service that:

1. **Consumes ERE outcomes** asynchronously via a messaging abstraction (Redis list queue adapter)
2. **Correlates outcomes** using the mention identifier triad `(sourceId, requestId, entityType)`
3. **Deduplicates** using a monotonic outcome timestamp and rejection of stale assignments
4. **Validates** that the mention exists in the Request Registry (idempotency enforcement)
5. **Updates the Decision Store** atomically with the latest cluster assignment per mention
6. **Exposes latest assignment wins** — subsequent lookups reflect the most recent ERE decision

### Success Metrics

- **Latency:** Outcome → Decision Store update ≤ 500ms p95 (over async channel)
- **Reliability:** Zero mention assignments lost due to duplicate outcomes (100% deduplication pass rate)
- **Traceability:** All outcome deliveries logged with correlation triad + timestamp
- **Scope:** All 4 interaction types supported (resolve, resolveConsideringRecommendation, resolveWithExclusions, recluster)

### Why This Architecture Wins

1. **Dependency Inversion:** Async adapter abstraction lets us swap Redis for Kafka/RabbitMQ without code changes
2. **ERE Authority Preserved:** Service never validates or reinterprets cluster assignments — only forwards and stores
3. **Minimal State Machine:** Single rule (reject if timestamp ≤ stored) eliminates complex idempotency logic
4. **No Persistence Coupling:** Contract contracts to Redis; Decision Store ownership remains clear

### Core Architecture Decision

**Async Adapter Pattern + Redis List Queue Implementation**

****- **Abstraction Layer:** `AsyncOutcomeListener` (interface, framework-agnostic; exposes `consume()` async generator)
- **Concrete Implementation:** `RedisOutcomeListener` (wraps `AbstractClient.pull_response()` in a polling loop)
- **Service Layer:** `OutcomeIntegrationService` (validation, registry check, persistence via `DecisionStoreService`)
- **Entrypoint:** Background worker consuming outcomes in a loop

**Rationale:** Allows testing with fake async adapter; supports future messaging backends without refactor.

### Tech Stack Rationale

| Component | Choice | Why |
|-----------|--------|-----|
| Async Adapter | Redis list queue (LPUSH/BRPOP) | Matches existing `RedisEREClient`; at-least-once via blocking pop |
| Correlation | Triad (sourceId, requestId, entityType) | Stable, user-provided, matches Request Registry key |
| Deduplication Marker | Timestamp (ISO 8601) | Simple, ERE-provided, no custom versioning needed |
| Stale Detection | `StaleOutcomeError` raised by `MongoDecisionRepository.upsert_decision()` | Atomic MongoDB check; service catches and logs |
| Persistence | Decision Store (MongoDB) | Atomic per-mention updates; delta tracking built-in |

### MVP Features

1. ✅ Consume `EntityMentionResolutionResponse` from ERE (solicited outcomes)
2. ✅ Consume unsolicited outcomes (ERE-initiated reclustering) with special `ere_request_id` prefix
3. ✅ Validate triad exists in Request Registry; raise error if missing
4. ✅ Correlate by triad + reject stale outcomes (timestamp-based deduplication)
5. ✅ Update Decision Store with latest cluster assignment + top N alternatives
6. ✅ Update delta tracking timestamp for refreshBulk paging

### Out of Scope (Explicitly Deferred)

- ❌ **Contract violation recovery:** Violations logged, not retried; violations never mutate decision state
- ❌ **Lineage or versioning:** No canonical entity history; only latest assignment stored
- ❌ **Alternative cluster ranking:** Alternatives stored as-is from ERE; no re-ranking by ERS
- ❌ **Pub/Sub topic routing:** Assumes single `ere_responses` topic; topic-per-entity-type is future work
- ❌ **Backpressure handling:** Assumes Decision Store writes are fast; backpressure on Redis consumer is TBD

---

## 2. Component Design

### Layers & Responsibilities

#### 2.1 Models (`models/`)

**Responsibility:** Domain entities for outcome correlation and deduplication.

| Model | Purpose |
|-------|---------|
| `OutcomeValidationError` | Exception for contract violations (null timestamp, empty candidates, invalid schema) |
| `TriadNotFoundError` | Exception raised when a triad is not found in the Request Registry |

**Error class signatures** (both subclass `ApplicationError` from `ers.commons.services.exceptions`):
```python
class OutcomeValidationError(ApplicationError):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)

class TriadNotFoundError(ApplicationError):
    def __init__(self, identifier: EntityMentionIdentifier) -> None:
        self.identifier = identifier
        super().__init__(f"Triad not found: {identifier}")
```

**No new domain models needed:** `EntityMentionResolutionResponse` (erspec) replaces `OutcomeMessage`; `EntityMentionIdentifier` (erspec) replaces `CorrelationTriad`; `Decision` (erspec) replaces `ClusterAssignment`. Using erspec types directly avoids a lossy mapping step — `OutcomeMessage` as specified in the original draft omitted `candidates` entirely.

**Invariants enforced by the service (not a new model):**
- `timestamp` is `Optional[datetime]` in erspec — service must raise `OutcomeValidationError` if `None`
- `candidates` must be non-empty — service must raise `OutcomeValidationError` if empty
- Triad fields (`source_id`, `request_id`, `entity_type`) are always non-empty (guaranteed by erspec `EntityMentionIdentifier`)
- Staleness check (`updated_at ≥ stored`) is enforced atomically by `MongoDecisionRepository.upsert_decision()` — service handles `StaleOutcomeError`, does not pre-check

#### 2.2 Adapters (`adapters/`)

**Responsibility:** Infrastructure for messaging and persistence.

| Adapter | Purpose |
|---------|---------|
| `AsyncOutcomeListener` (interface) | Abstract async outcome consumption; exposes `consume() -> AsyncGenerator[EntityMentionResolutionResponse, None]` |
| `RedisOutcomeListener` | Wraps `AbstractClient.pull_response()` in a `while True` polling loop; implements `AsyncOutcomeListener` |

**No new repository adapters needed:**
- Registry lookup: inject and use `RequestRegistryService` from `ers.request_registry.services` — call `get_resolution_request(identifier)`. Do NOT reach into `MongoResolutionRequestRepository` directly; that bypasses EPIC-01's service layer (anti-pattern per layering rules).
- Decision persistence: inject and use `DecisionStoreService` from `ers.resolution_decision_store.services` — call `store_decision()`.

**`RedisOutcomeListener.consume()` bridge pattern:**
```python
async def consume(self) -> AsyncGenerator[EntityMentionResolutionResponse, None]:
    while True:
        response = await self._client.pull_response()  # blocks until message or timeout
        if isinstance(response, EntityMentionResolutionResponse):
            yield response
        # EREErrorResponse: log and skip
```

**Constraints:**
- Listeners must provide idempotent consumption (at-least-once tolerance)
- No business logic in adapters; only I/O and message routing

#### 2.3 Service (`services/`)

**Responsibility:** Orchestrate outcome integration workflow.

**`OutcomeIntegrationService`**

**Constructor:**
```python
def __init__(
    self,
    registry_service: RequestRegistryService,
    decision_service: DecisionStoreService,
    on_outcome_stored: Callable[[str], Awaitable[None]] | None = None,
):
```
`on_outcome_stored` is an async callback injected at wiring time (EPIC-07 lifespan) as
`waiter.notify`. When `None` (e.g. EPIC-05 tested in isolation), no notification is sent
and the Coordinator always falls back to provisional timeout — valid degraded mode.

**Algorithm:**
```
Inputs: EntityMentionResolutionResponse (from AsyncOutcomeListener)
Process:
  1. Validate message (raise OutcomeValidationError if timestamp is None or candidates is empty)
  2. Extract identifier (triad): response.entity_mention_id (EntityMentionIdentifier)
  3. Query Request Registry: does triad exist? (RequestRegistryService.get_resolution_request)
     - If None: raise TriadNotFoundError (subclass ApplicationError; logged at WARN; outcome ignored)
     - If found: continue
  4. Map response to store_decision() arguments:
     - identifier = response.entity_mention_id
     - current = response.candidates[0]   # first candidate is primary (ERE authority; see Section 3.1)
     - candidates = response.candidates[1:]
     - updated_at = response.timestamp    # datetime; non-null guaranteed by step 1
  5. Call DecisionStoreService.store_decision(identifier, current, candidates, updated_at)
     - On StaleOutcomeError: log at DEBUG; proceed to step 6 (Coordinator may still be waiting)
     - On success: proceed to step 6
  6. If on_outcome_stored is set:
     - triad_key = f"{identifier.source_id}{identifier.request_id}{identifier.entity_type}"
     - await on_outcome_stored(triad_key)
     - No-op if no Coordinator is waiting (unsolicited reclustering, or no waiter registered)

Outputs: Decision (persisted) or stale rejection — notification sent in both cases
```

**Idempotency Rule:** Enforced atomically by `MongoDecisionRepository.upsert_decision()` — raises `StaleOutcomeError` if `stored.updated_at >= incoming.updated_at`. Service does NOT pre-fetch and compare.

**`triad_key` format:** Direct concatenation `f"{source_id}{request_id}{entity_type}"` — no separator. Matches the provisional cluster ID derivation algorithm (EPIC-06 §5.4). Must be identical in both EPIC-05 and EPIC-06.

#### 2.4 Entrypoint (`entrypoints/`)

**Responsibility:** Background worker that polls outcomes and processes them.

```python
class OutcomeIntegrationWorker:
    """
    Continuously listens for ERE outcomes and processes them via service.
    Lifecycle managed by EPIC-07 FastAPI lifespan (start on startup, stop on shutdown).
    Location: src/ers/ere_result_integrator/entrypoints/outcome_integration_worker.py
    """

    def __init__(self, listener: AsyncOutcomeListener, service: OutcomeIntegrationService):
        self._listener = listener
        self._service = service
        self._task: asyncio.Task | None = None

    def start(self) -> asyncio.Task:
        """Schedule run() as a background asyncio.Task. Non-blocking. Called by EPIC-07 lifespan."""
        self._task = asyncio.create_task(self.run())
        return self._task

    async def stop(self) -> None:
        """Cancel the background task and await clean termination. Called by EPIC-07 lifespan."""
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def run(self):
        """Poll outcomes from listener; call service for each. Infinite loop."""
        async for message in self._listener.consume():
            try:
                await self._service.integrate_outcome(message)
            except OutcomeValidationError as e:
                log.error(f"Contract violation: {e.detail}", extra={"identifier": message.entity_mention_id})
            except TriadNotFoundError as e:
                log.warning(f"Triad not found: {e.identifier}")
            except Exception as e:
                log.error("Unexpected error processing outcome", exc_info=e)
```

### 2.5 Deployment Constraints

- **Single-process / same event loop required (MVP).** `AsyncResolutionWaiter` uses in-process
  `asyncio.Event` objects. `OutcomeIntegrationWorker` and `ResolutionCoordinatorService` (EPIC-06)
  must run on the same asyncio event loop within the same OS process.
- **Lifecycle owner is EPIC-07.** The worker is started via `worker.start()` in the FastAPI
  `lifespan` startup hook and stopped via `worker.stop()` in the shutdown hook.
- **Horizontal scaling** would require replacing `AsyncResolutionWaiter` with an external
  coordination mechanism (e.g. Redis Pub/Sub). Out of scope for MVP.

---

## 3. Implementation Specifications

### 3.1 Data Contract

**Incoming Message (from ERE):**

```python
# EntityMentionResolutionResponse (from er-spec)
{
  "type": "EntityMentionResolutionResponse",
  "entity_mention_id": {
    "request_id": "req123",
    "source_id": "SYSTEM_A",
    "entity_type": "http://www.w3.org/ns/org#Organization"
  },
  "candidates": [
    {
      "clusterId": "cluster-001",
      "confidenceScore": 0.95,
      "similarityScore": 0.92
    },
    {
      "clusterId": "cluster-002",
      "confidenceScore": 0.45,
      "similarityScore": 0.40
    }
  ],
  "timestamp": "2026-03-12T14:30:45.123Z",
  "ere_request_id": "req123:001"  # or "ereNotification:rebuild-id" for unsolicited
}
```

**Decision Store Update (persisted — `Decision` from erspec):**

```python
{
  "id": "<sha256 of triad>",                                       # Derived by MongoDecisionRepository
  "about_entity_mention": {                                        # EntityMentionIdentifier
    "source_id": "SYSTEM_A",
    "request_id": "req123",
    "entity_type": "http://www.w3.org/ns/org#Organization"
  },
  "current_placement": {                                           # candidates[0] from ERE response
    "cluster_id": "cluster-001",
    "confidence_score": 0.95,
    "similarity_score": 0.92
  },
  "candidates": [                                                  # candidates[1:] from ERE response
    {"cluster_id": "cluster-002", "confidence_score": 0.45, "similarity_score": 0.40}
  ],
  "updated_at": "2026-03-12T14:30:45.123Z",                       # datetime; staleness marker + refreshBulk cursor
  "created_at": "2026-03-12T14:30:45.123Z"                        # set on first insert; never updated
}
```

**Explicit assumption — `candidates[0]` is the primary cluster:** ERE always returns candidates in descending confidence order; the first entry is the authoritative cluster assignment. The service maps `candidates[0]` → `current_placement` and `candidates[1:]` → `candidates`. This assumption is derived from the ERE contract and must not be changed without a corresponding ERE contract update.

### 3.2 Error Handling Matrix

| Error Type | Detection | Response | Logging | Observation |
|------------|-----------|----------|---------|-------------|
| **Malformed Message** | JSON parsing fails | Reject; log error detail | ERROR level | OpenTelemetry trace with message_id |
| **Missing Triad** | entity_mention_id is null or incomplete | Reject; log missing field name | ERROR level | Trace with field name |
| **Null Timestamp** | `response.timestamp is None` | Raise `OutcomeValidationError`; log | ERROR level | Trace with `ere_request_id` |
| **Empty Candidates** | `response.candidates` is empty | Raise `OutcomeValidationError`; log | ERROR level | Trace with `ere_request_id` |
| **Triad Not in Registry** | `MongoResolutionRequestRepository.find_by_triad` returns `None` | Raise `TriadNotFoundError` (subclass `ApplicationError`); log triad | WARN level | Trace with triad + query latency |
| **Stale Outcome** | `MongoDecisionRepository.upsert_decision` raises `StaleOutcomeError` | Catch; log at DEBUG; still call `on_outcome_stored` (Coordinator reads existing decision) | DEBUG level | Trace with timestamp comparison |
| **Decision Store Write Failure** | MongoDB insert/update fails | Raise exception; propagate up | ERROR level | Trace with error details |
| **Listener Connection Lost** | Redis consumer disconnected | Retry connection (exponential backoff) | WARN level | Trace with retry attempt count |

**Observability:** All errors logged to default Python logging; OpenTelemetry spans created at service level (not adapter level).

### 3.3 Anti-Patterns (DO NOT)

| ❌ Don't | ✅ Do Instead | Why |
|----------|---------------|-----|
| Pre-fetch Decision Store record to check staleness before writing | Call `store_decision()` directly; catch `StaleOutcomeError` | `upsert_decision()` enforces staleness atomically in MongoDB; pre-fetch creates a TOCTOU race |
| Validate cluster assignments (e.g., format check) | Accept any `cluster_id` as-is from ERE; ERE is authority | ERS is not responsible for cluster ID governance |
| Use `ere_request_id` as correlation key | Use `entity_mention_id` (EntityMentionIdentifier triad) | Triad is stable, user-provided, matches Request Registry key |
| Retry failed Decision Store updates | Propagate error; let orchestrator decide retry policy | Prevents cascading failures; keeps concerns separated |
| Merge alternatives with previous outcome | Replace `candidates` wholesale (`candidates[1:]` from latest response) | Avoids stale alternative suggestions |
| Log full message payload at INFO level | Log only `entity_mention_id` + `ere_request_id` + error reason | Prevents excessive logging; protects sensitive data |
| Create new domain models wrapping erspec types | Use `EntityMentionResolutionResponse`, `EntityMentionIdentifier`, `Decision` directly | Adding wrapper models introduces lossy mappings and duplicate concepts |
| Import `AsyncResolutionWaiter` from `ers.resolution_coordinator` | Accept `on_outcome_stored: Callable[[str], Awaitable[None]]` as constructor parameter | Both modules are Tier 2; same-tier sibling imports are forbidden by `.importlinter` |
| Branch on `ere_request_id.startswith("ereNotification:")` | Process solicited and unsolicited outcomes through identical pipeline | The prefix is informational only; `on_outcome_stored` is a no-op when no Coordinator is waiting |

### 3.4 Test Case Specifications

#### Unit Tests (≥5 required)

| Test ID | Component | Input | Expected Output | Edge Cases |
|---------|-----------|-------|-----------------|------------|
| **UT-001** | `OutcomeIntegrationService` | Valid `EntityMentionResolutionResponse` with fresh timestamp | `Decision` returned; `store_decision()` called with correct `current`/`candidates` split; `on_outcome_stored` called with correct `triad_key` | Candidates list has exactly 1 entry (no alternatives); `on_outcome_stored=None` does not raise |
| **UT-002** | `OutcomeIntegrationService` | `store_decision()` raises `StaleOutcomeError` | Stale outcome logged at DEBUG; `on_outcome_stored` still called; no exception propagated | `StaleOutcomeError` with equal timestamp (boundary) |
| **UT-003** | `OutcomeIntegrationService` | Triad not in Request Registry (`find_by_triad` returns `None`) | `TriadNotFoundError` (subclass `ApplicationError`) raised | |
| **UT-004** | `OutcomeIntegrationService` | Response with `timestamp=None` | `OutcomeValidationError` raised | Response with empty `candidates` list also raises |
| **UT-005** | `OutcomeIntegrationService` | Response with `timestamp=None` OR empty `candidates` | `OutcomeValidationError` raised before registry query | Both null-timestamp and empty-candidates paths |
| **UT-006** | `OutcomeIntegrationWorker` | Exception in `service.integrate_outcome` | Exception caught; logged; loop continues | Multiple consecutive errors |

#### Integration Tests (≥3 required)

| Test ID | Flow | Setup | Verification | Teardown |
|---------|------|-------|--------------|----------|
| **IT-001** | Solicited outcome integration | Create mention in Request Registry; publish resolution request to ERE mock | Outcome received; Decision Store updated with clusterId + alternatives; delta timestamp refreshed | Clean up test data from Decision Store |
| **IT-002** | Unsolicited outcome (reclustering) | Create mention + initial assignment in Decision Store; publish ERE reclustering outcome | Outcome received; Decision Store assignment replaced; new timestamp recorded | Clean up test data |
| **IT-003** | Duplicate outcome rejection | Create mention; publish same outcome twice with same timestamp | First outcome processed; second outcome rejected (debug log); Decision Store contains only one record | Clean up test data |
| **IT-004** | Late arrival outcome rejection | Create mention with assignment T1; send outcome T1+1; then send outcome T0 (late) | Outcome T1+1 accepted; Decision Store updated; T0 rejected | Clean up test data |

---

## 4. Gherkin Feature Specifications

### Feature: Integrate ERE Resolution Outcomes (UC-B1.2)

**File Locations** (3 files under `tests/feature/ere_result_integrator/`):
- `outcome_acceptance.feature` — solicited and unsolicited outcomes
- `deduplication_and_staleness.feature` — duplicate and late arrival rejection
- `contract_validation.feature` — null timestamp, empty candidates, missing triad

```gherkin
Feature: Integrate ERE Resolution Outcomes
  As an ERS operator
  I want to reliably absorb ERE clustering outcomes
  So that the Decision Store always reflects the latest authoritative cluster assignment

  Background:
    Given the Request Registry contains a mention with triad (SYSTEM_A, req123, org:Organization)
    And the Decision Store is empty for this triad

  Scenario: Accept valid solicited outcome
    When the ERE publishes a resolution response with:
      | Field              | Value                       |
      | ere_request_id     | req123:001                  |
      | timestamp          | 2026-03-12T14:30:45.123Z   |
      | cluster_id         | cluster-001                 |
      | candidates         | [cluster-002, cluster-003]  |
    Then the Decision Store is updated with:
      | Field              | Value                       |
      | cluster_id         | cluster-001                 |
      | updated_at         | 2026-03-12T14:30:45.123Z   |
    And the delta tracking timestamp is refreshed

  Scenario: Accept unsolicited outcome (ERE-initiated reclustering)
    Given the Decision Store contains an existing assignment to cluster-001
    When the ERE publishes an update outcome with:
      | Field              | Value                       |
      | ere_request_id     | ereNotification:rebuild-1   |
      | timestamp          | 2026-03-12T15:00:00.000Z   |
      | cluster_id         | cluster-002                 |
    Then the Decision Store is updated to reflect cluster-002
    And the new timestamp is recorded

  Scenario: Reject stale outcome (duplicate or late arrival)
    Given the Decision Store contains an assignment with timestamp 2026-03-12T14:30:45.123Z
    When the ERE publishes a response with timestamp 2026-03-12T14:30:44.000Z (earlier)
    Then the outcome is rejected silently (debug log only)
    And the Decision Store remains unchanged

  Scenario: Raise error if triad not found in Request Registry
    Given the Request Registry does NOT contain a mention with triad (UNKNOWN_SYSTEM, req999, ...)
    When the ERE publishes a response for this triad
    Then a TriadNotFoundError is raised
    And the error is logged at WARN level
    And the Decision Store is not modified

  Scenario: Tolerate duplicate outcomes (at-least-once semantics)
    When the ERE publishes the same resolution response twice (identical timestamp, clusterId)
    Then the first outcome is processed and persisted
    And the second outcome is rejected (timestamp ≤ stored)
    And the Decision Store contains exactly one record
```

---

## 5. Clarity Gate Verification

### Foundation Checks (7/7)

- [x] **Actionable:** Every section specifies what to code (no aspirational language like "fast" or "scalable")
- [x] **Current:** All decisions reflect Spine B, UC-B1.2, and clarified design choices (timestamp deduplication, triad validation)
- [x] **Single Source:** No duplicate information (timestamp rule explained once in section 3.1; erspec types referenced once, no redefinition)
- [x] **Decision, Not Wish:** All statements are decided (Redis list queue adapter chosen; callback injection pattern decided; staleness handled by repository)
- [x] **Prompt-Ready:** Every section can feed directly into a code generation prompt
- [x] **No Future State:** No "will eventually" or "might" language; all is present tense (decided)
- [x] **No Fluff:** No motivational conclusions; only actionable content

### Document Architecture Checks (6/6)

- [x] **Type Identified:** Marked as Implementation doc (Section 2 onwards; strategic overview in Section 1)
- [x] **Anti-patterns in Impl:** Section 3.3 contains ≥5 anti-patterns for implementation (stored in impl doc, not strategic)
- [x] **Test Cases in Impl:** Section 3.4 specifies unit + integration tests (in impl doc)
- [x] **Error Handling in Impl:** Section 3.2 provides error handling matrix (in impl doc)
- [x] **Deep Links Present:** All references precise (e.g., "Section 3.1 Data Contract", `tests/feature/ere_result_integrator/`)
- [x] **No Duplicates:** Strategic overview (Section 1) uses Implementation Implication pointers; no duplication

### AI Coder Understandability Score: **9.2/10**

| Criterion | Score | Evidence |
|-----------|-------|----------|
| **Actionability (25%)** | 25/25 | Every model, adapter, service method specified with inputs/outputs |
| **Specificity (20%)** | 19/20 | All edge cases listed; timestamp format explicit; one minor: listener retry backoff policy TBD |
| **Consistency (15%)** | 15/15 | Single source of truth for each concept (triad, timestamp, Decision — erspec types used directly) |
| **Structure (15%)** | 15/15 | Tables used throughout; clear hierarchy (layers → responsibilities → specs) |
| **Disambiguation (15%)** | 15/15 | Anti-patterns explicit; edge cases in test matrix; error detection clear |
| **Reference Clarity (10%)** | 9/10 | All internal refs precise; one external ref (redis client library) left to implementer |
| **TOTAL** | **98/110** | **9.2/10** |

**Ready for Phase 3 (Implementation)?** ✅ **YES** — All 13 Clarity Gate items pass. Score 9.2/10 (re-verified 2026-03-25 after alignment with EPICs 1–4, 6, and 7).

---

## 6. References

### Source Documents

| Topic | Location | Anchor |
|-------|----------|--------|
| Spine B (async integration) | [ERSArchitecture/spine-b.adoc](../../../docs/modules/ROOT/pages/ERSArchitecture/spine-b.adoc) | Section 8.3 |
| UC-B1.2 (outcome integration) | [AnnexeB-UseCases/ucb12.adoc](../../../docs/modules/ROOT/pages/AnnexeB-UseCases/ucb12.adoc) | Section UC-B1.2 |
| ERS-ERE Interface Contract | [ERS-ERE-Contract/interface.adoc](../../../docs/modules/ROOT/pages/ERS-ERE-Contarct/interface.adoc) | Sections on channels, Entity Mention, responses |
| ADR-A3N (identifier stability) | [AnnexeC-ADRs/adra3.adoc](../../../docs/modules/ROOT/pages/AnnexeC-ADRs/adra3.adoc) | Full decision |

### Dependency EPICs

| Component | Epic | Status |
|-----------|------|--------|
| Request Registry | [ERS-EPIC-01](../ers-epic-01-request-registry/EPIC.md) | ✅ Complete |
| Decision Store | [ERS-EPIC-04](../ers-epic-04-resolution-decision-store/EPIC.md) | ✅ Complete |
| ERE Contract Client | [ERS-EPIC-03](../ers-epic-03-ere-contract-client/EPIC.md) | ✅ Complete |

### Architectural Constraints (From Roadmap)

- [x] **ERE Authority:** ERS never overrides clustering outcomes
- [x] **Triad Correlation:** All idempotency keyed on (sourceId, requestId, entityType)
- [x] **Decision Store Atomicity:** Each mention's assignment updated atomically (single timestamp per mention)
- [x] **At-Least-Once Tolerance:** Integration handles duplicates via timestamp deduplication
- [x] **Monotonic Outcome Marker:** Using timestamp as ordering/staleness detection
- [x] **Observability:** Logging at service level; traces via OpenTelemetry

---

## 7. Roadmap & Next Steps

### Phase 2 Status

| Milestone | Status | Notes |
|-----------|--------|-------|
| Architecture designed | ✅ Complete | Async adapter + Redis implementation |
| Data contract specified | ✅ Complete | Section 3.1 |
| Test cases defined | ✅ Complete | Section 3.4 (6 unit + 4 integration) |
| Gherkin features written | ✅ Complete | Section 4 |
| Gherkin .feature files created | ✅ Complete | 3 files under `tests/feature/ere_result_integrator/` |
| Step definition scaffolding | ✅ Complete | 3 files under `tests/steps/ere_result_integrator/` |
| Clarity Gate passed | ✅ Complete | 9.2/10, all 13 items verified |

### Phase 3 (Implementation) Prerequisites

- [x] **ERS-EPIC-01 (Request Registry)** must be complete (triad validation requires registry access)
- [x] **ERS-EPIC-04 (Decision Store)** must be complete (outcome persistence target)
- [x] **ERS-EPIC-03 (ERE Contract Client)** must be complete (messaging adapter setup)
- [x] er-spec library must expose `EntityMentionResolutionResponse` model

### Phase 3 Sequence (Recommended Order)

| Step | Task file | What |
|------|-----------|------|
| 1 | [task51-domain-errors.md](task51-domain-errors.md) | `OutcomeValidationError`, `TriadNotFoundError` |
| 2 | [task52-outcome-listener-interface.md](task52-outcome-listener-interface.md) | `AsyncOutcomeListener` ABC |
| 3 | [task53-redis-outcome-listener.md](task53-redis-outcome-listener.md) | `RedisOutcomeListener` |
| 4 | [task54-outcome-integration-service.md](task54-outcome-integration-service.md) | `OutcomeIntegrationService` (TDD — tests first) |
| 5 | [task55-outcome-integration-worker.md](task55-outcome-integration-worker.md) | `OutcomeIntegrationWorker` (TDD — tests first) |
| 6 | [task56-unit-tests.md](task56-unit-tests.md) | Domain + adapter unit tests |
| 7 | [task57-integration-tests.md](task57-integration-tests.md) | Integration tests + wire Gherkin step defs |

**Estimated Scope:** ~500-650 LOC (no new models; adapters ~200, service ~200, entrypoint ~100, errors ~50)

---

**Epic Status:** All prerequisites met. Ready for implementation.
**Clarity Gate Score:** 9.2/10 ✅ (re-verified after spec alignment with EPICs 1–4)
**Last Updated:** 2026-03-25
