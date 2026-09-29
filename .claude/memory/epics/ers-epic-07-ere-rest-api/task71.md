# Task 7.1 — Establish a solid domain data model for ERS REST API

## Decision

Split `ers_rest_api/domain/data_transfer_objects.py` into three cohesive files
organised by endpoint concern:

| File             | Responsibility                                                    |
|------------------|-------------------------------------------------------------------|
| `resolution.py`  | `/resolve` and `/resolveBulk` — request, result, bulk envelope    |
| `lookup.py`      | `/lookup` and `/refreshBulk` — lookup request/response, bulk sync |
| `errors.py`      | Error envelope and error code enum (shared across all endpoints)  |

The original `data_transfer_objects.py` is kept as-is during the transition so
existing imports remain valid. It will be removed once all consumers are migrated
(a follow-up task).

## Key changes

### Base classes — `ERSRequest` / `ERSResponse`

Added `ERSRequest(FrozenDTO)` and `ERSResponse(FrozenDTO)` in
`ers.commons.domain.data_transfer_objects`. All ERS REST API request and response
DTOs inherit from these, mirroring the `ERERequest` / `EREResponse` pattern in
erspec. This provides an extraction point if these models are later promoted to
the erspec contract.

### Heavy reliance on erspec models

- **`EntityMentionIdentifier`** replaces flat `source_id` / `request_id` /
  `entity_type` fields in requests, results, and lookup responses. The triad
  is a first-class composed object.
- **`EntityType`** enum (from erspec) is validated on
  `EntityMentionResolutionRequest` via `@model_validator`, rejecting unsupported
  types like `UNKNOWN_TYPE`.
- **`ClusterReference`** (from erspec) is used in `LookupResponse`.

### Resolution module (`resolution.py`)

- **`EntityMentionResolutionRequest`** — request body for `/resolve` and each
  item in `/resolveBulk`. Uses `identified_by: EntityMentionIdentifier`.
- **`EntityMentionResolutionResult`** — unified result type for both single
  `/resolve` and per-item bulk results. Flat union with success fields
  (`canonical_entity_id`, `status`) XOR error fields (`error_code`, `detail`),
  enforced by `@model_validator`. For single resolve, errors are raised as
  exceptions (→ `ErrorResponse`); in bulk context, per-item errors use the
  error fields.
  **Flag:** if the internal coordinator result later needs extra metadata,
  extract a dedicated internal model at that point.
- **`BulkResolveRequest`** / **`BulkResolveResponse`** — bulk envelope DTOs.

### Lookup module (`lookup.py`)

- **`LookupRequest`** — wraps `identified_by: EntityMentionIdentifier` for
  GET `/lookup` query parameters.
- **`LookupResponse`** — unified model for both single lookup and bulk delta
  items. Contains `identified_by`, `cluster_reference`, and `last_updated`.
  Used as the response body for GET `/lookup` and as each item in
  `RefreshBulkResponse.deltas`.
- **`RefreshBulkRequest`** / **`RefreshBulkResponse`** — bulk sync DTOs with
  cursor-based pagination. `@model_validator` enforces `has_more` ↔
  `continuation_cursor` consistency.

### Errors module (`errors.py`)

- **`ErrorCode`** — `StrEnum` covering all Gherkin error codes:
  `VALIDATION_ERROR`, `IDEMPOTENCY_CONFLICT`, `MENTION_NOT_FOUND`,
  `SERVICE_ERROR`.
- **`ErrorResponse`** — standard error envelope.

### Removals / merges

- **`ResolveResponse` + `ResolutionResult`** → merged into
  `EntityMentionResolutionResult` with field `status` (not `outcome`).
- **`BulkResolveItemResult`** → merged into `EntityMentionResolutionResult`
  (same purpose, one unified type).
- **`DeltaAssignment`** → merged into `LookupResponse` (same structure and
  intent).
- **`DeltaPage`** → removed (unused).

### Kept Python snake_case

CamelCase JSON serialisation will be handled at the Pydantic `model_config`
level (`alias_generator`) when wiring endpoints — not in the domain DTOs.

## File layout after this task

```
src/ers/commons/domain/
└── data_transfer_objects.py       # added ERSRequest, ERSResponse

src/ers/ers_rest_api/domain/
├── __init__.py
├── data_transfer_objects.py       # legacy — kept until consumers migrate
├── resolution.py                  # NEW
├── lookup.py                      # NEW
└── errors.py                      # NEW
```
