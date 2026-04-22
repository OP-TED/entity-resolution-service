# Entity Resolution Service

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0.0-informational)](src/VERSION)

ERS is the coordination backbone of an entity resolution platform. It receives RDF entity mention submissions, registers them, and orchestrates their resolution through a pluggable Entity Resolution Engine (ERE) over Redis. For each mention it returns a canonical cluster identifier — either confirmed by the ERE or provisionally issued when the engine does not respond within the configured time budget.

The system is engine-authoritative: the ERE determines canonical identity, ERS never overrides it. ERS persists the latest resolution decision per mention, exposes assignments through a REST API, and routes human curation recommendations back to the ERE for re-evaluation. It is not a master data platform, not a golden-record system, and does not clean or enrich incoming data.

---

## Getting Started

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

### 3. Start the stack

```bash
make up       # start all services (Curation API, ERS API, Redis, FerretDB, Postgres)
make logs     # follow service logs
make down     # stop all services

Note: `make up` creates a shared external network `ersys-local` used for cross-component communication.
To remove it manually: `docker network rm ersys-local`
```

| Service | URL |
|---------|-----|
| Curation API | `http://localhost:8000` |
| ERS REST API | `http://localhost:8001` |
| FerretDB (MongoDB) | `localhost:27017` |
| Redis | `localhost:6379` |

### What this stack does NOT include

This repo starts the ERS backend and its infrastructure (Redis, database). It does **not** include the Entity Resolution Engine (ERE) or the web UI.

Without ERE running and connected to the **same Redis instance**, entity mentions will be accepted and registered but resolution will never complete — ERS will issue provisional cluster IDs until the ERE responds.

- To add ERE: follow the Getting Started section in [entity-resolution-engine-basic](https://github.com/OP-TED/entity-resolution-engine-basic#getting-started).
- To add the web UI: follow the Getting Started section in [entity-resolution-service-webapp](https://github.com/OP-TED/entity-resolution-service-webapp#getting-started).

---

## Application configuration

### `src/config/rdf_mention_config.yaml`

Maps RDF entity types to extraction rules used when parsing incoming entity mentions. It tells ERS how to identify each entity type in RDF and which property paths to follow when extracting attribute values.

**`namespaces`** — prefix registry used to resolve shortened property paths throughout the file. Each entry maps a prefix (e.g. `epo`) to its full IRI base (e.g. `http://data.europa.eu/a4g/ontology#`). All prefixes used in `fields` values must be declared here.

**`entity_types`** — one entry per supported entity type (e.g. `ORGANISATION`, `PROCEDURE`). Each entry contains:

| Key | Type | Purpose |
|-----|------|---------|
| `rdf_type` | prefixed IRI string | RDF class that identifies this entity type (e.g. `org:Organization`) |
| `fields` | mapping of field name → property path | Attributes to extract; `/` separates hops for multi-step traversal (e.g. `cccev:registeredAddress/epo:hasCountryCode`) |

Field names defined here must match the field names expected by the Entity Resolution Engine. To add a new entity type, add a new key under `entity_types` with its `rdf_type` and the `fields` to extract. To add a new attribute to an existing type, add a new key under its `fields` mapping with the corresponding RDF property path.

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
