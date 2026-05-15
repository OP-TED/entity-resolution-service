# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [unreleased]

## [1.1.0] - 2026-05-15
### Added
* Immediate provisional mode: setting `ERS_COORDINATOR_SINGLE_TIME_BUDGET=0` or `ERS_COORDINATOR_BULK_TIME_BUDGET=0` returns a provisional identifier without waiting for ERE
* Stateless multi-instance deployment via Redis Pub/Sub cross-instance notification — coordinators on separate instances signal each other when a resolution outcome arrives
* Optional TLS support for Redis connections via `REDIS_TLS` environment variable
* `ServiceUnavailableError` propagated as HTTP 503 on MongoDB and Redis infrastructure outages — `resolve`, curation, and lookup endpoints return a structured error response instead of crashing
* Configurable entity display name field per entity type; returned by the `/entity-types` discovery endpoint
* Exponential backoff with jitter for `OutcomeIntegrationWorker` reconnect on Redis failures
* Socket connect timeout for the Redis subscriber worker
* Black-box end-to-end ERSys test suite migrated from er-ops
* `ERS_SUBSCRIBER_READY_TIMEOUT` environment variable for startup readiness gate
* Environment variables index added to README

### Changed
* `ERE_REQUEST_CHANNEL` / `ERE_RESPONSE_CHANNEL` renamed to `ERSYS_REQUEST_CHANNEL` / `ERSYS_RESPONSE_CHANNEL` — update `.env` files accordingly
* `display_name_field` property renamed to `entity_label_field` in entity-type configuration
* Error field in REST API responses renamed from `error` to `message`; `SERVICE_UNAVAILABLE` added to all error enums
* `POST /refreshBulk` now returns only decisions whose cluster placement changed, reducing payload size for unchanged entities
* Startup readiness gate and MongoDB-fallback safety net added to coordinator startup
* Dependency versions pinned to exact values for reproducible builds

### Fixed
* Redis subscriber: reconnect backoff now resets on successful subscribe; subscribed event cleared on `stop()`; `aclose()` guaranteed to run when unsubscribe is cancelled; malformed Pub/Sub payloads skipped instead of crashing
* Redis client: `TimeoutError` in `publish_notification` now wrapped correctly
* Configuration: identifier property path and `full_address` field corrected for real TED data

## [1.0.0-rc.1] - 2026-04-21
### Added
* Entity resolution pipeline — six core components implemented end-to-end: Request Registry (immutable intake records, idempotency enforcement, snapshot watermarks), RDF Mention Parser (SPARQL-based, configuration-driven extraction), ERE Contract Client (async Redis publisher/subscriber), Resolution Decision Store (MongoDB, optimistic concurrency), ERE Result Integrator (async outcome consumer with at-least-once delivery handling), and Resolution Coordinator (time-budget enforcement, provisional identifier issuance, bulk decomposition)
* ERS REST API (FastAPI): `POST /resolve` — entity mention intake with canonical or provisional cluster ID response (Spine A); `GET /lookup` and `POST /lookup-bulk` — current cluster assignment retrieval (Spine C); `POST /refreshBulk` — delta of changed assignments since last snapshot (Spine C); `GET /entity-types` — supported entity type discovery
* Curation application: human-in-the-loop decision review interface with `POST /accept` / `POST /reject` bulk operations, role-based user management, user action audit log, user search by email, and automatic ERE re-evaluation request on every curation action
* Resolution lookup context enrichment — optional `context` field on `/lookup` and `/refreshBulk` delta entries carrying the original request context from the Request Registry
* OpenTelemetry tracing: SDK integration with structured span naming, auto-instrumentation for FastAPI and async Redis calls, and configurable OTLP exporter
* CI/CD pipeline: GitHub Actions workflow with SonarCloud quality gate, `ruff` linting, `mypy` strict type checking, `importlinter` architecture contract enforcement, and staging environment deployment dispatch
