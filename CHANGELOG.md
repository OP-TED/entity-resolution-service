# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [unreleased]


## [1.1.0-rc.6] - 2026-07-16

### Fixed
* Faulty healthcheck command in docker compose and CI scripts (TEDSWS-516)

### Removed
* SonarCloud integration, as it depended on contractor-specific configuration (TEDSWS-528)


## [1.0.0-rc.2] - 2026-06-30

### Added
* Filtering by decision status (TEDSWS-524)
* Curator review indicators in the decision list and decision details view (TEDSWS-522)
* Support for sending rejection decisions to the ERE (TEDSWS-530)

### Changed
* ERSys installation instructions and related documentation improved (TEDSWS-520)
* Contractor-specific references removed from the source code repositories (TEDSWS-528)

### Fixed
* Decision status persistence after browser refresh (TEDSWS-512)


## [1.1.0-rc.4] - 2026-06-30

### Changed
* Dockerfile updated to use fully qualified Docker Hub reference for the Python base image


## [1.1.0-rc.3] - 2026-06-10

### Added
* Curation decisions are now sorted by cluster size — clusters with more entities surface first in browsing responses
* `cluster_size` and `reviewed_since_placement` fields on decision rows — enables per-cluster review-progress display and filtering by review status
* Review counter in decision summary responses — reports how many decisions in each request set have been reviewed since placement
* Cluster-size index: a materialised index tracking the size of every cluster, updated atomically on accept/reject actions
* Decision browsing filter by `reviewed_since_placement` status
* User-action idempotency: repeated curator actions on the same decision are detected and silently ignored
* Reject action now excludes the current cluster placement from the candidate set
* Operational scripts: `backfill_cluster_sizes` and `verify_cluster_sizes` for upgrading existing deployments; `backfill_previous_review_count` for the review-counter backfill; all scripts documented in `INSTALL.md` and `Makefile`

### Fixed
* Decision store: decision document is now rewritten on any material outcome change, preventing stale decisions surviving ERE re-evaluation rounds
* Decision store: `$addFields` stage in cluster-size aggregation pipeline now runs before the cursor predicate (query correctness fix)
* Curation: TOCTOU race condition on concurrent curator actions closed via atomic claim
* Cluster-size index: entries with a zero count are deleted rather than stored
* Backfill script: `reviewed_since_placement` is derived from the maximum action date during backfill
* Seed script: `seed_db` now populates `cluster_sizes` after seeding decisions

### Changed
* Removed contractor contact references and attributions from source files, documentation, and licence

## [1.1.0-rc.2] - 2026-05-15
### Added
* Immediate provisional mode: setting `ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET=0` returns a provisional identifier without waiting for ERE
* Stateless multi-instance deployment via Redis Pub/Sub cross-instance notification — coordinators on separate instances signal each other when a resolution outcome arrives
* Optional TLS support for Redis connections via `REDIS_TLS` environment variable
* `ServiceUnavailableError` propagated as HTTP 503 on MongoDB and Redis infrastructure outages — `resolve`, curation, and lookup endpoints return a structured error response instead of crashing
* Configurable entity display name field per entity type; returned by the `GET /curation/entity-types` discovery endpoint
* Exponential backoff with jitter for `OutcomeIntegrationWorker` reconnect on Redis failures
* Socket connect timeout for the Redis subscriber worker
* Black-box end-to-end ERSys test suite migrated from er-ops
* `ERS_SUBSCRIBER_READY_TIMEOUT` environment variable for startup readiness gate
* Notable environment variables documented in README with defaults and descriptions

### Changed
* `ERE_REQUEST_CHANNEL` / `ERE_RESPONSE_CHANNEL` renamed to `ERSYS_REQUEST_QUEUE` / `ERSYS_RESPONSE_QUEUE` — update `.env` files accordingly
* `display_name_field` property renamed to `entity_label_field` in entity-type configuration
* Error field in REST API responses renamed from `error` to `message`; `SERVICE_UNAVAILABLE` added to all error enums
* `POST /refresh-bulk` now returns only decisions whose cluster placement changed, reducing payload size for unchanged entities
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
