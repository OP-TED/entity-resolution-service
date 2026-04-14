# Entity Resolution Service

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.4.0-informational)](VERSION)

ERS is the coordination backbone of an entity resolution platform. It receives RDF entity mention submissions, registers them, and orchestrates their resolution through a pluggable Entity Resolution Engine (ERE) over Redis. For each mention it returns a canonical cluster identifier — either confirmed by the ERE or provisionally issued when the engine does not respond within the configured time budget.

The system is engine-authoritative: the ERE determines canonical identity, ERS never overrides it. ERS persists the latest resolution decision per mention, exposes assignments through a REST API, and routes human curation recommendations back to the ERE for re-evaluation. It is not a master data platform, not a golden-record system, and does not clean or enrich incoming data.

---

## Requirements
 
- Python 3.12+
- Docker + Docker Compose
- [Poetry](https://python-poetry.org/) 2.x
- **External Infrastructure:**
  - Redis (for ERE orchestration)
  - MongoDB (via FerretDB)
  - PostgreSQL (backend for FerretDB)


---

## Installation

```bash
git clone https://github.com/meaningfy-ws/entity-resolution-service.git
cd entity-resolution-service
make install
```

Configure the environment:

```bash
cp infra/.env.example infra/.env
# Edit infra/.env — set MongoDB URI, Redis URL, ports
```

---

## Running

```bash
make up        # start all services
make rebuild   # rebuild Docker images and start
make down      # stop all services
make logs      # follow service logs
```

The API is available at `http://localhost:${UVICORN_PORT:-8000}`.

---

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

---

## Contributing

Read [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for setup, coding standards, testing expectations, and PR guidelines. Please follow our [Code of Conduct](docs/CODE_OF_CONDUCT.md).

---

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
