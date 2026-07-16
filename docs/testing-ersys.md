# Testing ERSys — Running Black-Box Tests from the ERS Repo

This document explains how to set up the infrastructure and run the full ERSys
black-box test suite from this repository. These tests target the complete
ERSys stack (ERS + ERE + Webapp) running locally via Docker Compose.


## Prerequisites

- Docker + Docker Compose v2
- The three component repos cloned locally and their stacks set up
- Poetry (for the ERS repo Python environment)


## Infrastructure Setup

Which components you need depends on which test suite you want to run:

| Suite | What must be running |
|-------|----------------------|
| `smoke/` | ERS (API + Curation + Redis + FerretDB) **+ Webapp** |
| `e2e/curation_api/` | ERS (API + Curation + Redis + FerretDB) |
| `e2e/ers_api/` | ERS (API + Curation + Redis + FerretDB) |
| `e2e/ere_async/` | ERS **+ ERE worker** |
| `e2e/full_cycle/` | ERS **+ ERE worker** |
| All (`make test-ersys-all`) | ERS + ERE + Webapp |

See the [Installation Guide](../INSTALL.md) for step-by-step instructions to set up
the full ERSys stack (ERS + ERE + Webapp). All three components must join the
same Docker network (`ersys-local`).


## Environment Configuration

The tests read configuration from the `.env` files of the component repos.
Point to these files via environment variables before running any test:

| Env var | Points to | Default |
|---------|-----------|---------|
| `ERE_ENV_FILE` | `src/infra/.env` inside the ERE repo | _(not loaded)_ |
| `WEBAPP_ENV_FILE` | `src/infra/.env` inside the Webapp repo | _(not loaded)_ |
| `ERS_ENV_FILE` | `src/infra/.env` inside the ERS repo | `src/infra/.env` in this repo |

Files are merged in this order — ERS is loaded last and wins on any conflicts.

**Setup:**

```bash
# Point to each component repo's env file:
export ERS_ENV_FILE=/path/to/entity-resolution-service/src/infra/.env
export ERE_ENV_FILE=/path/to/entity-resolution-engine-basic/src/infra/.env
export WEBAPP_ENV_FILE=/path/to/entity-resolution-service-webapp/src/infra/.env

# ERS_ENV_FILE defaults to src/infra/.env in this repo, so if you are
# running tests from the ERS repo itself you can skip that export.
```

Required variables and where they come from:

| Variable | Source | Purpose | Default |
|----------|--------|---------|---------|
| `STACK_HOST` | _(not in any .env.example)_ | Hostname for all stack ports | `localhost` (injected) |
| `ERS_API_PORT` | ERS `.env` | ERS REST API port | `8001` |
| `UVICORN_PORT` | ERS `.env` | Curation API port | `8000` |
| `WEBAPP_PORT` | _(not in any .env.example)_ | Webapp port | `8080` (injected) |
| `REDIS_HOST` | ERS `.env` | Redis hostname | `ersys-redis` ⚠️ |
| `REDIS_PORT` | ERS `.env` | Redis port | `6379` |
| `REDIS_PASSWORD` | ERS `.env` | Redis password | `changeme` |
| `MONGO_URI` | ERS `.env` | MongoDB/FerretDB connection URI | `mongodb://...@localhost:27017` |
| `MONGO_DATABASE_NAME` | ERS `.env` | Database name | `ers` |
| `ADMIN_EMAIL` | ERS `.env` | Curation API admin account | `admin@ers.local` |
| `ADMIN_PASSWORD` | ERS `.env` | Curation API admin password | `changeme` |

> ⚠️ **Host-machine networking:** `.env` uses Docker service names (`ersys-redis`,
> `ferretdb`) that only resolve inside the Docker network. **Do not change `.env`** —
> Docker Compose reads it too. Instead, export overrides in your shell before running
> tests:
> ```bash
> export REDIS_HOST=localhost
> export MONGO_URI="mongodb://username:password@localhost:27017"
> ```
> Shell env vars take precedence over file values in the test conftest.

> **`STACK_HOST` and `WEBAPP_PORT`** are not exported by any component `.env.example`.
> The conftest injects `localhost` and `8080` as defaults so tests work out of the box
> on a standard local stack. Override by adding them to your `ERS_ENV_FILE`.


## Running Tests

```bash
# Install test dependencies (one-time)
make install

# Check stack reachability (requires make up)
make test-ersys-smoke

# Full black-box e2e suite (requires full ERSys stack)
make test-ersys-e2e

# Everything
make test-ersys-all
```

Smoke tests verify port reachability and Redis/MongoDB connectivity.
E2e tests exercise the full resolution cycle, curation API, and ERE async flow.


## Test Structure

```
test/ersys/
├── conftest.py          # env loading, markers, test-data fixtures
├── e2e/                 # black-box e2e scenarios
│   ├── conftest.py      # HTTP clients, state clients, scenario cleanup
│   ├── curation_api/    # Curation API boundary tests
│   ├── ers_api/         # ERS REST API boundary tests
│   ├── ere_async/       # ERE async queue tests
│   └── full_cycle/      # end-to-end resolution cycle
├── smoke/               # stack reachability probes
├── manual/              # .http files for manual exploration
└── test_data/           # RDF/TTL fixtures, sample configs
```


## Debugging

If tests fail to connect, verify:

```bash
docker compose -f src/infra/compose.dev.yaml ps   # all services Up
docker exec ersys-redis redis-cli -a changeme ping # Redis reachable
```

For ERE async tests: the ERE worker must be running and connected to the same
Redis instance. Set `ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET=0` in ERS env
to skip ERE and receive provisional IDs immediately (useful for isolated testing).


## Manual Testing

The `.http` files in `test/ersys/manual/` contain HTTP requests in a format-agnostic
notation conformant with RFC 7230. Each file implements a set of testing scenarios
described in its inline comments. The intended use is to run them manually and observe
the API responses from the ERSys APIs. Requests target the ERS REST API, the Curation
API, and — where Redis state needs to be inspected or injected — a dedicated HTTP
wrapper for Redis.

**Tools**

Two tools can execute `.http` files:

- **httpyac CLI** — a Node.js command-line runner:
  ```bash
  npm install -g httpyac          # one-time install
  httpyac test/ersys/manual/full_cycle/resolution_cycle_simple.http
  ```
- **[REST Client](https://marketplace.visualstudio.com/items?itemName=humao.rest-client)
  VS Code extension** — provides in-editor send buttons and response inspection panels.
- **Other IDEs** — equivalent capabilities are available either built-in or via similar
  plugins in most modern IDEs.

**Scenarios**

- `clustering/` — single and multi-cluster formation from identical/distinct mentions
- `full_cycle/` — resolution, curation, and refresh-bulk flows end-to-end

**Environment**

`http-client.env.json` in the manual directory defines shared variables
(`ers_api_url`, `curation_api_url`, `inject_ere_response_api`, credentials).
Configuration of these variables may differ depending on the tooling used; consult
your tool's documentation to learn how to apply them.
