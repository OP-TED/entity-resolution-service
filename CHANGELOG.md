# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [unreleased]

## [1.0.0-rc.1] - 2026-04-21
### Added
* Entity resolution pipeline — six core components implemented end-to-end: Request Registry (immutable intake records, idempotency enforcement, snapshot watermarks), RDF Mention Parser (SPARQL-based, configuration-driven extraction), ERE Contract Client (async Redis publisher/subscriber), Resolution Decision Store (MongoDB, optimistic concurrency), ERE Result Integrator (async outcome consumer with at-least-once delivery handling), and Resolution Coordinator (time-budget enforcement, provisional identifier issuance, bulk decomposition)
* ERS REST API (FastAPI): `POST /resolve` — entity mention intake with canonical or provisional cluster ID response (Spine A); `GET /lookup` and `POST /lookup-bulk` — current cluster assignment retrieval (Spine C); `POST /refreshBulk` — delta of changed assignments since last snapshot (Spine C); `GET /entity-types` — supported entity type discovery
* Curation application: human-in-the-loop decision review interface with `POST /accept` / `POST /reject` bulk operations, role-based user management, user action audit log, user search by email, and automatic ERE re-evaluation request on every curation action
* Resolution lookup context enrichment — optional `context` field on `/lookup` and `/refreshBulk` delta entries carrying the original request context from the Request Registry
* OpenTelemetry tracing: SDK integration with structured span naming, auto-instrumentation for FastAPI and async Redis calls, and configurable OTLP exporter
* CI/CD pipeline: GitHub Actions workflow with SonarCloud quality gate, `ruff` linting, `mypy` strict type checking, `importlinter` architecture contract enforcement, and staging environment deployment dispatch
