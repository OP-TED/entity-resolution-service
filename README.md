# Entity Resolution Service

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.1.0-informational)](src/VERSION)

ERS is the coordination backbone of an entity resolution platform. It receives RDF entity mention submissions, registers them, and orchestrates their resolution through a pluggable Entity Resolution Engine (ERE) over Redis. For each mention it returns a canonical cluster identifier — either confirmed by the ERE or provisionally issued when the engine does not respond within the configured time budget.

The system is engine-authoritative: the ERE determines canonical identity, ERS never overrides it. ERS persists the latest resolution decision per mention, exposes assignments through a REST API, and routes human curation recommendations back to the ERE for re-evaluation. It is not a master data platform, not a golden-record system, and does not clean or enrich incoming data.

---

## Getting Started

**To set up the complete ERSys stack** (ERS + ERE + Webapp), see the [Installation Guide](INSTALL.md).

The instructions below cover running ERS on its own.

### Prerequisites

- Python 3.12+
- [Poetry](https://python-poetry.org/) 2.x
- Docker + Docker Compose

### 1. Clone and install

```bash
git clone https://github.com/OP-TED/entity-resolution-service.git
cd entity-resolution-service
make install
```

### 2. Configure the environment

```bash
cp src/infra/.env.example src/infra/.env
```

The defaults work for local development. Notable variables in `src/infra/.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `UVICORN_PORT` | `8000` | Curation API port |
| `ERS_API_PORT` | `8001` | ERS REST API port |
| `REDIS_HOST` | `ersys-redis` | Redis host (joins shared ersys-local network) |
| `REDIS_PASSWORD` | `changeme` | Redis password — **must match ERE** |
| `ADMIN_EMAIL` | `admin@ers.local` | Default admin account |
| `ADMIN_PASSWORD` | `changeme` | Default admin password |
| `ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET` | `30` | Seconds ERS waits per mention for an ERE response before issuing a provisional identifier. Set to `0` to skip ERE entirely and issue provisional IDs immediately (no Redis required). |
| `ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET` | `120` | Outer timeout in seconds for a bulk resolution request covering all mentions. Set to `0` to remove the outer timeout; use with `ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET=0` for fully immediate provisional bulk mode. |

### 3. Start the stack

```bash
make up       # start all services (Curation API, ERS API, Redis, FerretDB, Postgres)
make logs     # follow service logs
make down     # stop all services

Note: `make up` creates a shared external network `ersys-local` used for cross-component communication.
To remove it manually: `docker network rm ersys-local`
```

> **Rebuilding with a clean cache:** If you have upgraded the source or made changes to the
> Docker image and suspect a stale build, force a full rebuild without Docker layer cache:
> ```bash
> make rebuild-clean
> ```

| Service | URL |
|---------|-----|
| Curation API | `http://localhost:8000` |
| ERS REST API | `http://localhost:8001` |
| FerretDB (MongoDB) | `localhost:27017` |
| Redis | `localhost:6379` |

### What this stack does NOT include

This repo starts the ERS backend and its infrastructure (Redis, database). It does **not** include the Entity Resolution Engine (ERE) or the web UI.

Without ERE running and connected to the **same Redis instance**, entity mentions will be accepted and registered but resolution will never complete — ERS will issue provisional cluster IDs until the ERE responds.

To skip ERE submission entirely and receive provisional identifiers immediately (no Redis required), set both `ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET=0` and `ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET=0`. This is useful for environments where ERE is not deployed and provisional IDs are the intended steady-state output.

- To add ERE and the web UI: see the [Installation Guide](INSTALL.md) for the full ERSys stack setup.

---

## Application configuration

ERS is configured through environment variables and the YAML mapping file
`src/config/rdf_mention_config.yaml`, which defines how RDF entity types are parsed and
which attributes are extracted from each. The full reference for both — including all
environment variables, their defaults, and the structure of the mapping file — is in
[docs/configuration.md](docs/configuration.md).

## Development

```bash
make test             # all tests with coverage
make test-unit        # unit tests only (no infrastructure needed)
make test-feature     # BDD / Gherkin feature tests
make lint             # ruff check
make typecheck        # mypy
make check-quality    # lint + typecheck + architecture boundaries
make ci-full          # full CI pipeline — run before opening a PR
```

### OpenAPI schemas (`resources/`)

The `resources/` directory contains the generated OpenAPI schemas for both APIs:

- `ers-openapi-schema.json` — ERS REST API
- `curation-openapi-schema.json` — Curation API

Generate or refresh them with:

```bash
make openapi
```

These files are committed to the repository. The [entity-resolution-service-webapp](https://github.com/OP-TED/entity-resolution-service-webapp) fetches them from this repo at build time to generate its API client.

### ERSys black-box tests

A separate suite of black-box tests targets the full running stack (ERS + ERE + Webapp)
and lives in `test/ersys/`:

```bash
make test-ersys-smoke   # stack reachability checks (requires make up)
make test-ersys-e2e     # full black-box e2e suite (requires full ERSys stack)
make test-ersys-all     # smoke + e2e
```

See [docs/testing-ersys.md](docs/testing-ersys.md) for setup instructions, required env files, and which components each suite needs.

> **Running tests from the host machine:** The default `REDIS_HOST=ersys-redis` in
> `src/infra/.env` is a Docker-internal hostname not resolvable from the host.
> Override it in your shell before running any test target:
> ```bash
> export REDIS_HOST=localhost
> ```
> Do not change `src/infra/.env` — Docker Compose reads that file at startup.

### Observability (optional)

```bash
make up-with-dev-tools    # start stack + Jaeger tracing UI (http://localhost:16686)
make down-with-dev-tools  # stop stack + Jaeger
```

See [docs/telemetry.md](docs/telemetry.md) for configuration and usage.

Pre-commit hooks (format + lint on every commit):

```bash
poetry run pre-commit install
```

For AI-assisted development, see [`CLAUDE.md`](CLAUDE.md) and the [`.claude/memory`](.claude/memory) folder for architecture specs, epic planning, and agent configuration.


## Repository Layout

This repository follows the repository owner's requirements for project structure, which place the self-contained Python project (source code, dependencies, and tooling config) under `src/`. This layout is required for the repository owner's deployment tooling to locate and operate the project correctly.

The canonical `Makefile` lives at the repo root and owns all build logic. Recipes invoke `cd src &&` internally so that Poetry, Ruff, mypy, and pytest all resolve correctly against the `src/` project. All `make` targets are run from the repo root — no need to `cd src` first.


---

## Contributing

Read [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for setup, coding standards, testing expectations, and PR guidelines. Please follow our [Code of Conduct](docs/CODE_OF_CONDUCT.md).

---

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
