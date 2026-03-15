# Epic: ERS-EPIC-03 — ERE Contract Client

## Status
- **Epic ID:** ERS-EPIC-03
- **Component:** #3 — ERE Contract Client
- **Phase:** Planning
- **Spines:** B (Async Engine Interaction), D (Manual Curation — forwarding curator recommendations)
- **Last updated:** 2026-03-12
- **Dependencies:** er-spec library (domain models), ERS-ERE contract specification (interface.adoc)
- **Clarity Gate:** 9.7/10

---

# Part 1 — Specification

**Document type:** Implementation

## 1. Description

The ERE Contract Client is the adapter and thin service that publishes entity resolution requests from ERS to ERE via Redis. It implements the ERS-to-ERE direction of the asynchronous contract defined in `interface.adoc` and `ADR-C2N`.

This component is a **publish-only** transport adapter at the service level. The adapter layer itself is read+write capable (supporting both `lpush` to `ere_requests` and `brpop` from `ere_responses`) to allow reuse by EPIC-05 (ERE Result Integrator), but the service exposed by this epic wraps only the publish path.

The component is a pure transport layer. It does not:
- Make clustering decisions (ERE authority)
- Manage time budgets or provisional identifiers (Resolution Coordinator, EPIC-06)
- Consume responses (ERE Result Integrator, EPIC-05)
- Validate business rules beyond envelope completeness

All action types (`resolve`, `resolveConsideringRecommendation`, `reResolveConsideringExclusions`, `recluster`) flow through the same `ere_requests` channel, differentiated by the `actionType` field in a unified resolution envelope.

## 2. Glossary

| Term | Definition |
|------|-----------|
| **Correlation Triad** | `(sourceId, requestId, entityType)` — the sole correlation key for all ERS-ERE message exchange. Present in every request and response. |
| **Unified Resolution Envelope** | Single message structure for all ERS-to-ERE interactions. Contains `actionType`, `entity_mention`, and optional `proposed_cluster_ids` / `excluded_cluster_ids`. Per ADR-C2N. |
| **Action Type** | Discriminator field in the resolution envelope: `resolve`, `resolveConsideringRecommendation`, `reResolveConsideringExclusions`, `recluster`. |
| **ere_requests** | Redis List channel. ERS pushes requests via `lpush`. ERE consumes via `brpop`. |
| **ere_responses** | Redis List channel. ERE pushes responses via `lpush`. ERS consumes via `brpop`. Used by EPIC-05, not this component's service. |
| **Fire-and-Forget** | Publishing semantics: successful `lpush` (returns list length > 0) is sufficient confirmation. No acknowledgement from ERE expected. |
| **At-Least-Once Delivery** | Messages may be duplicated or reordered. All consumers must be idempotent. Per ADR-C2N. |
| **ere_request_id** | Auto-generated per-request identifier (e.g., UUID). Used by ERE internally for request-response matching. |
| **er-spec** | Shared library providing Pydantic domain models: `EntityMentionResolutionRequest`, `EntityMentionResolutionResponse`, `EREErrorResponse`, `EntityMention`, `EntityMentionIdentifier`, `ClusterReference`. |

## 3. Scope

### In Scope
- Redis adapter: `lpush` to `ere_requests`, `brpop` from `ere_responses` (read capability for EPIC-05 reuse)
- Redis connection configuration (host, port, db, channel names)
- Thin publish service: construct request envelope from domain objects, validate envelope, serialize via Pydantic, push to Redis
- Serialization: Pydantic `.model_dump_json()` for serialization, `.model_validate_json()` for deserialization
- All four action types through unified envelope
- Service-level observability (OpenTelemetry spans and structured logging)
- Connection health check (Redis ping)

### Out of Scope
- Response consumption logic (EPIC-05)
- Time-budget management and provisional ID issuance (EPIC-06)
- Business rule validation beyond envelope completeness (EPIC-06)
- ERE-internal processing
- Redis cluster/sentinel configuration (EPIC-X cross-cutting)
- Retry policies on publish failure (EPIC-06 decides retry strategy)

### Assumptions
1. er-spec models (`EntityMentionResolutionRequest` and related) are Pydantic models with `.model_dump_json()` / `.model_validate_json()` support.
2. Redis is available as a single-instance service for MVP. Cluster/sentinel is out of scope.
3. Channel names (`ere_requests`, `ere_responses`) match the existing basic ERE implementation.
4. `ere_request_id` is auto-generated (UUID4) by the service before publishing.
5. The adapter is instantiated with a Redis connection (or config) and is stateless beyond the connection.

## 4. Domain Models

All models are imported from the `er-spec` library. No new domain models are defined by this component.

### 4.1 Models from er-spec (used, not defined here)

| Model | Module | Key Fields |
|-------|--------|-----------|
| `EntityMentionResolutionRequest` | `erspec.models.ere` | `entity_mention`, `ere_request_id`, `timestamp`, `proposed_cluster_ids`, `excluded_cluster_ids` |
| `EntityMentionResolutionResponse` | `erspec.models.ere` | `entity_mention_id`, `candidates`, `timestamp`, `ere_request_id` |
| `EREErrorResponse` | `erspec.models.ere` | `ere_request_id`, `errorType`, `errorTitle`, `errorDetail` |
| `EntityMention` | `erspec.models.core` | `identifier`, `content`, `content_type` |
| `EntityMentionIdentifier` | `erspec.models.core` | `source_id`, `request_id`, `entity_type` |
| `ClusterReference` | `erspec.models.core` | `clusterId`, `confidenceScore`, `similarityScore` |

### 4.2 Local Configuration Model

```python
class RedisConnectionConfig(BaseModel):
    """Redis connection parameters for the ERE contract channels."""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    request_channel: str = "ere_requests"
    response_channel: str = "ere_responses"
    socket_timeout: float | None = 5.0       # seconds; None = no timeout
    socket_connect_timeout: float | None = 5.0
```

**Constraints:**
- `port` must be 1-65535.
- `db` must be >= 0.
- Channel names must be non-empty strings.
- Timeout values, when set, must be > 0.
- All values overridable via environment variables (prefix `ERS_REDIS_`).

## 5. Behavioural Specification

### Request Publishing (Service)

1. The service receives an `EntityMentionResolutionRequest` (already constructed by the caller, typically the Resolution Coordinator).
2. The service validates that the request contains a non-empty `entity_mention` with a complete identifier triad (`source_id`, `request_id`, `entity_type`).
3. If `ere_request_id` is not set, the service generates one (UUID4 string).
4. If `timestamp` is not set, the service sets it to `datetime.utcnow()`.
5. The service serializes the request to JSON via `request.model_dump_json()`.
6. The service calls the adapter's `push_request` method, which performs `lpush(request_channel, json_bytes)`.
7. The adapter returns the new list length (int). Any value >= 1 confirms successful enqueue.
8. The service logs the publish event (triad + ere_request_id + action type) at INFO level.
9. On Redis connection failure, the adapter raises `RedisConnectionError`. The service does NOT retry (caller decides).

### Response Reading (Adapter only — for EPIC-05)

10. The adapter exposes `subscribe_responses() -> Generator[EntityMentionResolutionResponse | EREErrorResponse, None, None]`.
11. Internally uses `brpop(response_channel, timeout)` in a loop.
12. Deserializes via Pydantic `.model_validate_json()`.
13. Yields each parsed response object.
14. On deserialization failure, logs ERROR and skips the malformed message (does not crash the generator).

### Health Check

15. The adapter exposes `ping() -> bool` that returns `True` if Redis responds to PING.

## 6. Error Catalogue

| Error Type | Layer | Detection | Response | Log Level |
|------------|-------|-----------|----------|-----------|
| `RedisConnectionError` | adapter | Redis client raises `redis.ConnectionError` or `redis.TimeoutError` | Wrap in domain `RedisConnectionError`; propagate to caller | ERROR |
| `InvalidRequestError` | service | Missing triad fields or missing `entity_mention` | Raise before attempting publish | ERROR |
| `SerializationError` | service | Pydantic `.model_dump_json()` raises | Wrap in domain `SerializationError`; propagate | ERROR |
| `DeserializationError` | adapter | Pydantic `.model_validate_json()` raises on response | Log ERROR + skip message; do not crash generator | ERROR |
| `ChannelUnavailableError` | adapter | `lpush` returns 0 or raises unexpected Redis error | Wrap in domain `ChannelUnavailableError` | ERROR |

All error types defined in a local `models/errors.py` module. Each inherits from a base `EREContractError`.

## 7. Task Breakdown and Roadmap

### Task 1: Define Error Models and Configuration
**Layer:** `models/`
**Dependencies:** None
**Description:**
- Create `models/errors.py` with base `EREContractError` and all five error subclasses (`RedisConnectionError`, `InvalidRequestError`, `SerializationError`, `DeserializationError`, `ChannelUnavailableError`).
- Create `models/config.py` with `RedisConnectionConfig` Pydantic model including field validators (port range, non-empty channels, positive timeouts).
- Environment variable loading via Pydantic `model_config` with `env_prefix = "ERS_REDIS_"`.

**Acceptance Criteria:**
- All error classes instantiable with message string.
- `RedisConnectionConfig()` produces valid defaults.
- Invalid port (0, 65536), empty channel name, negative timeout all rejected by validation.
- Environment variables override defaults.

### Task 2: Implement Redis Adapter
**Layer:** `adapters/`
**Dependencies:** Task 1 (errors, config)
**Description:**
- Create `adapters/redis_ere_adapter.py` with `RedisEREAdapter` class.
- Constructor accepts `RedisConnectionConfig` or pre-built `redis.Redis` client.
- Methods: `push_request(request_json: str) -> int`, `subscribe_responses(timeout: int = 0) -> Generator`, `ping() -> bool`.
- Adapter is a thin wrapper: serialization/deserialization logic stays at the boundary (service for serialization, adapter only for deserialization of responses).
- Map all `redis.*` exceptions to domain error types.

**Acceptance Criteria:**
- `push_request` calls `lpush` on `request_channel` and returns list length.
- `subscribe_responses` yields deserialized response objects; skips malformed messages.
- `ping` returns True/False without raising.
- Redis exceptions mapped to domain errors (never leaking `redis.ConnectionError` etc.).

### Task 3: Implement Publish Service
**Layer:** `services/`
**Dependencies:** Tasks 1 + 2
**Description:**
- Create `services/ere_publish_service.py` with `EREPublishService` class.
- Constructor: `__init__(self, adapter: RedisEREAdapter)`.
- Method: `publish_request(request: EntityMentionResolutionRequest) -> str` (returns `ere_request_id`).
- Validates triad completeness. Auto-generates `ere_request_id` (UUID4) if absent. Sets `timestamp` if absent.
- Serializes via Pydantic, delegates to adapter.
- OpenTelemetry span: `ere_contract_client.publish` with attributes: `source_id`, `request_id`, `entity_type`, `ere_request_id`, `action_type`.
- Structured logging at INFO (success) and ERROR (failure).

**Acceptance Criteria:**
- Returns `ere_request_id` on success.
- Raises `InvalidRequestError` for incomplete triad.
- Does not retry on `RedisConnectionError` (propagates).
- OTel span created with correct attributes.
- Works identically for all four action types.

### Task 4: Unit Tests
**Layer:** `tests/`
**Dependencies:** Tasks 1-3
**Description:**
- Unit tests for `RedisConnectionConfig` validation.
- Unit tests for all error classes.
- Unit tests for `RedisEREAdapter` using a mock Redis client.
- Unit tests for `EREPublishService` using a mock adapter.
- Minimum 90% coverage on all three modules.

**Acceptance Criteria:**
- All test cases from Section 8 pass.
- Coverage >= 90%.

### Task 5: Integration Tests
**Layer:** `tests/`
**Dependencies:** Tasks 1-3
**Description:**
- Integration tests using a real Redis instance (via testcontainers or local Redis).
- Full round-trip: push a request, verify it appears in the Redis list.
- Response subscription: push a response to `ere_responses`, verify adapter yields it.
- Health check against live Redis.

**Acceptance Criteria:**
- All integration test cases from Section 8 pass.
- Tests are skippable if Redis is unavailable (pytest mark).

### Task 6: Gherkin Features
**Layer:** `tests/features/`
**Dependencies:** Tasks 1-3
**Description:**
- Feature files for publish scenarios and error scenarios.
- Step definitions calling the service and adapter.

**Acceptance Criteria:**
- All Gherkin scenarios from Section 11 pass via pytest-bdd.

## Roadmap
- [ ] Task 1: Define Error Models and Configuration (models)
- [ ] Task 2: Implement Redis Adapter (adapters)
- [ ] Task 3: Implement Publish Service (services)
- [ ] Task 4: Unit Tests (tests)
- [ ] Task 5: Integration Tests (tests)
- [ ] Task 6: Gherkin Features (tests/features)

## 8. Test Case Specifications

### Unit Tests

| Test ID | Component | Input | Expected Output | Edge Cases |
|---------|-----------|-------|-----------------|------------|
| TC-001 | RedisConnectionConfig | Default constructor | Valid config: localhost:6379/0, channels set | N/A |
| TC-002 | RedisConnectionConfig | port=0 | ValidationError | port=65536; port=-1 |
| TC-003 | RedisConnectionConfig | request_channel="" | ValidationError | response_channel="" |
| TC-004 | RedisConnectionConfig | socket_timeout=-1.0 | ValidationError | socket_timeout=0.0 |
| TC-005 | RedisConnectionConfig | env vars set | Config picks up env values | Partial env override (only host) |
| TC-006 | EREContractError hierarchy | Instantiate each error | All 5 are instances of EREContractError | str(error) includes message |
| TC-007 | RedisEREAdapter.push_request | Valid JSON string + mock Redis | lpush called on correct channel; returns list length | Empty string JSON |
| TC-008 | RedisEREAdapter.push_request | Mock Redis raises ConnectionError | Raises domain RedisConnectionError | TimeoutError variant |
| TC-009 | RedisEREAdapter.subscribe_responses | Mock brpop returns valid JSON | Yields deserialized response object | Multiple consecutive messages |
| TC-010 | RedisEREAdapter.subscribe_responses | Mock brpop returns malformed JSON | Logs ERROR, skips, continues | Partial JSON; non-UTF8 bytes |
| TC-011 | RedisEREAdapter.ping | Mock Redis ping returns True | Returns True | Redis raises = returns False |
| TC-012 | EREPublishService.publish_request | Valid request with full triad | Adapter.push_request called; returns ere_request_id | Request with all optional fields |
| TC-013 | EREPublishService.publish_request | Request missing source_id | Raises InvalidRequestError | Missing request_id; missing entity_type; missing entity_mention entirely |
| TC-014 | EREPublishService.publish_request | Request without ere_request_id | UUID4 generated and set | Request without timestamp |
| TC-015 | EREPublishService.publish_request | Adapter raises RedisConnectionError | Propagated unchanged to caller | ChannelUnavailableError variant |
| TC-016 | EREPublishService.publish_request | Request with proposed_cluster_ids | Same publish path; no special handling | excluded_cluster_ids; both set |
| TC-017 | EREPublishService observability | Valid publish | OTel span created with correct attributes | Error case: span records exception |

### Integration Tests

| Test ID | Flow | Setup | Verification | Teardown |
|---------|------|-------|--------------|----------|
| IT-001 | Push request to Redis | Start Redis; create adapter + service | Request JSON appears in `ere_requests` list via `rpop` | Flush test DB |
| IT-002 | Subscribe responses | Push valid response JSON to `ere_responses` via `lpush` | Generator yields correct response object | Flush test DB |
| IT-003 | Subscribe responses (malformed) | Push invalid JSON to `ere_responses` | Generator skips bad message; yields next valid one | Flush test DB |
| IT-004 | Health check | Start Redis | `ping()` returns True | None |
| IT-005 | Health check (down) | No Redis running | `ping()` returns False | None |

## 9. Anti-Patterns (DO NOT)

| Don't | Do Instead | Why |
|-------|-----------|-----|
| Import `redis` library in the service layer | Keep all `redis.*` imports in `adapters/redis_ere_adapter.py` only | DIP: services depend on adapter abstraction, not infrastructure library |
| Implement retry logic in the adapter or service | Let the caller (Resolution Coordinator, EPIC-06) decide retry strategy | SRP: transport adapter publishes; orchestrator decides retry policy |
| Use LinkML JSONDumper for serialization | Use Pydantic `.model_dump_json()` / `.model_validate_json()` | ERS uses Pydantic models; LinkML dumper is for ERE-internal use only |
| Log raw `entity_mention.content` (RDF payload) | Log only triad fields + ere_request_id + action_type | PII risk; payload size; same constraint as EPIC-02 |
| Catch and swallow `RedisConnectionError` silently | Propagate to caller; let caller decide how to handle | Fire-and-forget means no retry, not silent failure |
| Add business validation (e.g., entity type checking) in the contract client | Validate only envelope completeness (triad present); business rules belong in EPIC-06 | SRP: this is a transport adapter, not a business rule engine |
| Put OTel spans or logging in the adapter layer | Keep all observability in `EREPublishService` (service layer) | Architectural constraint #9: observability at service level only |
| Hardcode channel names or connection parameters | Use `RedisConnectionConfig` with env var overrides | Deployment flexibility; testability |
| Create new model classes duplicating er-spec models | Import `EntityMentionResolutionRequest` etc. from `erspec.models` | Architectural constraint #10: reuse er-spec models exclusively |
| Use Redis pub/sub mechanism | Use Redis Lists (`lpush`/`brpop`) | Must match existing basic ERE implementation transport |

## 10. Architectural Constraints

1. **ERE Authority:** This component does not make or influence clustering decisions. It is a pure message transport.
2. **Triad Correlation:** Every published message contains the complete triad `(sourceId, requestId, entityType)`. Validated before publish.
3. **Observability at Service Level:** OTel spans and structured logs in `EREPublishService` only. Adapter has no logging beyond ERROR for deserialization failures (response path).
4. **Reuse er-spec Models:** All message types from `erspec.models`. Only `RedisConnectionConfig` and error types defined locally.
5. **Layering:** `models/` = config + errors. `adapters/` = Redis interaction. `services/` = publish orchestration + observability. No reverse dependencies.
6. **Fire-and-Forget Publishing:** Successful `lpush` is sufficient. No acknowledgement protocol.
7. **At-Least-Once Tolerance:** Consumers (EPIC-05) must be idempotent. This component may publish the same request more than once if the caller retries.
8. **Adapter Reuse by EPIC-05:** The `subscribe_responses` method on the adapter is defined here but consumed by EPIC-05's service layer.

## 11. Dependencies and Integration Points

| Dependency | Type | Provides | Status |
|-----------|------|----------|--------|
| **er-spec** | Library | `EntityMentionResolutionRequest`, `EntityMentionResolutionResponse`, `EREErrorResponse`, `EntityMention`, `EntityMentionIdentifier` | Available (v0.2.0-rc.2) |
| **redis-py** | Package | `redis.Redis` client, `lpush`, `brpop`, connection management | Available (>= 5.0) |
| **Pydantic** | Package | Model serialization/deserialization, config validation | Available (>= 2.0) |
| **OpenTelemetry** | Package | Tracing spans, structured logging | Available |

### Downstream Consumers
| Consumer | What It Uses | Epic |
|----------|-------------|------|
| Resolution Coordinator | `EREPublishService.publish_request()` | ERS-EPIC-06 |
| ERE Result Integrator | `RedisEREAdapter.subscribe_responses()` | ERS-EPIC-05 |
| Link Curation REST API (via Coordinator) | `EREPublishService.publish_request()` for re-resolve with exclusions | ERS-EPIC-09 |

## 12. Concrete Examples

### Example 1: Simple resolve request (action type: resolve)
```json
{
  "type": "EntityMentionResolutionRequest",
  "entity_mention": {
    "identifier": {
      "request_id": "324fs3r345vx",
      "source_id": "TEDSWS",
      "entity_type": "http://www.w3.org/ns/org#Organization"
    },
    "content": "epd:ent005 a org:Organization; ...",
    "content_type": "text/turtle"
  },
  "timestamp": "2026-01-14T12:34:56Z",
  "ere_request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

### Example 2: Resolve with proposed placements (action type: resolveConsideringRecommendation)
```json
{
  "type": "EntityMentionResolutionRequest",
  "entity_mention": {
    "identifier": {
      "request_id": "324fs3r345vx",
      "source_id": "TEDSWS",
      "entity_type": "http://www.w3.org/ns/org#Organization"
    },
    "content": "epd:ent005 a org:Organization; ...",
    "content_type": "text/turtle"
  },
  "proposed_cluster_ids": ["324fs3r345vx-aa32wa", "324fs3r345vx-bb45we"],
  "timestamp": "2026-01-14T12:34:56Z",
  "ere_request_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901"
}
```

### Example 3: Re-resolve with exclusions (action type: reResolveConsideringExclusions)
```json
{
  "type": "EntityMentionResolutionRequest",
  "entity_mention": {
    "identifier": {
      "request_id": "324fs3r345vxab",
      "source_id": "TEDSWS",
      "entity_type": "http://www.w3.org/ns/org#Organization"
    },
    "content": "epd:ent005 a org:Organization; ...",
    "content_type": "text/turtle"
  },
  "excluded_cluster_ids": ["324fs3r345vx-bb45we", "324fs3r345vx-cc67ui"],
  "timestamp": "2026-01-14T12:40:56Z",
  "ere_request_id": "c3d4e5f6-a7b8-9012-cdef-123456789012"
}
```

## 13. Gherkin Feature Outline

At `tests/features/ere_contract_client/`:

### Feature: Publish Resolution Request to ERE

| Scenario | Description |
|----------|-------------|
| Publish simple resolve request | Happy path: request with full triad serialized and pushed to `ere_requests` |
| Publish resolve with proposed placements | Request with `proposed_cluster_ids` pushed identically |
| Publish resolve with exclusions | Request with `excluded_cluster_ids` pushed identically |
| Publish resolve with both proposals and exclusions | Both optional fields set; same publish path |
| Auto-generate ere_request_id | Request without `ere_request_id` gets UUID4 assigned |
| Auto-set timestamp | Request without `timestamp` gets current UTC time |

### Feature: Reject Invalid Requests

| Scenario | Description |
|----------|-------------|
| Reject request missing source_id | InvalidRequestError raised before publish |
| Reject request missing request_id | InvalidRequestError raised before publish |
| Reject request missing entity_type | InvalidRequestError raised before publish |
| Reject request missing entity_mention | InvalidRequestError raised before publish |

### Feature: Handle Redis Failures

| Scenario | Description |
|----------|-------------|
| Redis connection refused | RedisConnectionError raised; no silent swallow |
| Redis timeout on push | RedisConnectionError raised |
| Redis health check succeeds | ping() returns True |
| Redis health check fails | ping() returns False |

## 14. References

| Topic | Location | Section |
|-------|----------|---------|
| ERE Interface Contract | `docs/modules/ROOT/pages/ERS-ERE-Contarct/interface.adoc` | Requests channel, Entity Mention Resolution Request |
| ERE Response Contract | `docs/modules/ROOT/pages/ERS-ERE-Contarct/interface.adoc` | Entity Mention Resolution Response, Error Response |
| Spine B (async interaction) | `docs/modules/ROOT/pages/ERSArchitecture/spine-b.adoc` | Section 8.3 |
| ADR-C1N (Client Resolution Semantics) | `docs/modules/ROOT/pages/AnnexeC-ADRs/adrc1.adoc` | Full section |
| ADR-C2N (Message Types and Delivery) | `docs/modules/ROOT/pages/AnnexeC-ADRs/adrc2.adoc` | Full section |
| er-spec ERE models | `https://github.com/OP-TED/entity-resolution-spec` | `erspec.models.ere` |
| er-spec core models | `https://github.com/OP-TED/entity-resolution-spec` | `erspec.models.core` |
| Basic ERE Redis implementation | `entity-resolution-engine-basic/src/ere/entrypoints/redis.py` | `RedisEREClient` class |
| Basic ERE AbstractClient | `entity-resolution-engine-basic/src/ere/entrypoints/__init__.py` | `AbstractClient` interface |
| Planning roadmap | `.claude/memory/planning-roadmap.md` | Component #3 |

---
<!-- implementation-log -->
---

# Part 2 — Implementation Log

<!-- Written and updated by the implementer during Phase 3. -->

---

## Clarity Gate Assessment

**Document type:** Implementation | **Date:** 2026-03-12

### 13-Item Checklist

#### Foundation Checks
- [x] **Actionable** -- Concrete classes, methods, error types, config model, JSON examples throughout.
- [x] **Current** -- Reflects developer answers from 2026-03-12 Q&A session and existing basic ERE implementation analysis.
- [x] **Single Source** -- er-spec models referenced by pointer only (Section 4.1); not redefined. Config model defined locally (Section 4.2).
- [x] **Decision, Not Wish** -- All decided: Redis Lists transport, Pydantic serialization, fire-and-forget semantics, UUID4 for ere_request_id, service-only observability.
- [x] **Prompt-Ready** -- Every section usable as direct implementer input with concrete interfaces, field names, and behavioural steps.
- [x] **No Future State** -- No "might", "eventually", "ideally". EPIC-05 and EPIC-06 responsibilities explicitly deferred.
- [x] **No Fluff** -- No motivational content. Pure specification.

#### Document Architecture Checks
- [x] **Type Identified** -- Implementation (stated in header after Part 1 heading).
- [x] **Anti-patterns Placed** -- Section 9, 10 entries (exceeds minimum of 5).
- [x] **Test Cases Placed** -- Section 8, 17 unit tests + 5 integration tests.
- [x] **Error Handling Placed** -- Section 6, 5 error types with layer, detection, response, and log level.
- [x] **Deep Links Present** -- Section 14, 10 references with file paths and section anchors.
- [x] **No Duplicates** -- er-spec models listed as reference table (not redefined); config model defined once.

### Scoring

| Criterion | Weight | Score | Rationale |
|-----------|--------|-------|-----------|
| Actionability | 25% | 10 | Concrete interfaces, method signatures, behavioural steps 1-15, JSON examples |
| Specificity | 20% | 10 | Channel names, serialization mechanism, UUID4 strategy, port ranges, timeout values all explicit |
| Consistency | 15% | 10 | Single source for config; er-spec by pointer; no duplication |
| Structure | 15% | 10 | Tables throughout; numbered behavioural spec; clear task breakdown |
| Disambiguation | 15% | 9 | 10 anti-patterns; 5 errors; edge cases per test. Minor gap: adapter constructor flexibility (config vs. pre-built client) could be more prescriptive on when to use which |
| Reference Clarity | 10% | 10 | 10 deep links with file paths and section identifiers |

**Score: 9.85/10** -- Weighted: (10*0.25 + 10*0.20 + 10*0.15 + 10*0.15 + 9*0.15 + 10*0.10) = 9.85. Rounded to **9.8/10** -- PASS. Ready for implementation.
