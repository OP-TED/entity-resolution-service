# ERSys Installation Guide

This guide walks you through setting up the complete Entity Resolution System
(ERSys) on a single machine using Docker Compose.

## What is ERSys?

ERSys is a platform that identifies when different records refer to the same
real-world entity (e.g. two organizations with slightly different names that are
actually the same company). It consists of three components, each in its own
repository:

- **Entity Resolution Service (ERS)** — the central backend. It receives entity
  data, stores it, and coordinates the resolution process. It exposes two APIs:
  the Curation API (used by the Webapp) and the ERS REST API (used to submit and
  query entity data).
- **Entity Resolution Engine (ERE)** — the processing engine. It does the actual
  matching and clustering work: comparing entities, calculating similarity, and
  deciding which records belong together. It has no web interface — it works in
  the background, connected to ERS through a message queue (Redis).
- **Webapp** — the user interface. A web application where human operators can
  review, verify, and curate the entity resolution results produced by ERS and
  ERE.

ERS also runs the shared infrastructure that the other components depend on:
**Redis** (the message queue that connects ERS and ERE) and **FerretDB** (a
MongoDB-compatible database that stores entity data, backed by PostgreSQL).

---

## Prerequisites

| Requirement | Minimum version | How to check |
|-------------|-----------------|--------------|
| Docker Engine | 24+ | `docker --version` |
| Docker Compose V2 | 2.22+ (plugin) | `docker compose version` |
| Git | 2.x | `git --version` |

> Docker Compose V2 ships as a Docker plugin. You run it as `docker compose`
> (with a space), not `docker-compose` (with a hyphen). The compose files in
> ERSys use the `develop.watch` feature, which requires Compose 2.22 or later.


---

## Step 1: Create the shared Docker network

The three ERSys components run in separate Docker containers but need to
communicate with each other. They do this over a shared Docker network.

Create it before starting any services:

```bash
docker network create ersys-local
```

You only need to do this once. The network persists until you remove it
(see [Stopping the stack](#stopping-the-stack)).

> `make up` in each repo also creates this network if it doesn't exist
> (`docker network create ersys-local || true`). Creating it manually
> beforehand ensures it's ready before any service starts.

---

## Step 2: Start ERS

Start ERS first — it runs Redis and the database, which the other components
depend on.

### Clone and configure

```bash
git clone https://github.com/OP-TED/entity-resolution-service.git
cd entity-resolution-service
cp src/infra/.env.example src/infra/.env
```

The defaults in `.env` work for local development. Key variables:

| Variable | Default | What it controls |
|----------|---------|------------------|
| `UVICORN_PORT` | `8000` | Port for the Curation API |
| `ERS_API_PORT` | `8001` | Port for the ERS REST API |
| `REDIS_PASSWORD` | `changeme` | Password for Redis — **must match ERE** |
| `ADMIN_EMAIL` | `admin@ers.local` | Default admin login email |
| `ADMIN_PASSWORD` | `changeme` | Default admin login password |

### Start the services

```bash
make up
```

This builds the Docker images and starts five containers: the Curation API, the
ERS REST API, Redis, FerretDB, and PostgreSQL. The first build takes a few
minutes; subsequent starts are much faster.

> **Sample data is loaded automatically.** The development compose file sets
> `SEED_DB=true` for the Curation API (overriding the `.env` default of `false`),
> so the database is populated with sample data on startup. The Webapp will have
> something to display right away. You do not need to change anything in `.env`.

### Verify

Open these URLs in a browser — you should see a JSON response with
`"status": "ok"`:

- [http://localhost:8000/health](http://localhost:8000/health) — Curation API
- [http://localhost:8001/health](http://localhost:8001/health) — ERS REST API

Alternatively, run from a terminal:

```bash
curl http://localhost:8000/health    # Curation API
curl http://localhost:8001/health    # ERS REST API
```

---

## Step 3: Start ERE

ERE is the background processing engine. It connects to the Redis instance
started by ERS, listens for incoming resolution requests, and sends back
clustering results. It has no web interface or API endpoint.

### Clone and configure

```bash
git clone https://github.com/OP-TED/entity-resolution-engine-basic.git
cd entity-resolution-engine-basic
cp src/infra/.env.example src/infra/.env
```

The defaults in `.env` are already aligned with ERS. Key variables:

| Variable | Default | Must match |
|----------|---------|------------|
| `REDIS_HOST` | `ersys-redis` | The Redis container name from ERS |
| `REDIS_PASSWORD` | `changeme` | **ERS `REDIS_PASSWORD`** |
| `ERSYS_REQUEST_QUEUE` | `ere_requests` | Must match ERS |
| `ERSYS_RESPONSE_QUEUE` | `ere_responses` | Must match ERS |

### Disable ERE's built-in Redis

ERE ships with its own Redis service for standalone use. Since ERS already
provides Redis, running both causes a port conflict. You need to disable ERE's
Redis before starting.

Open the file `src/infra/compose.dev.yaml` in a text editor and **comment out
the `ersys-redis` and `redisinsight` service blocks** by adding `#` at the
start of each line:

```yaml
services:
  # ersys-redis:
  #   image: redis:7.4.4-alpine
  #   container_name: "ersys-redis"
  #   ...all lines until the next service...
  # redisinsight:
  #   image: redis/redisinsight:3.2.0
  #   container_name: "redisinsight"
  #   ...all lines until the next service...
  ere:
    ...leave this one as-is...
```

> **Tip:** In YAML, a `#` at the start of a line makes it a comment, so Docker
> ignores it. Make sure every line of the `ersys-redis` and `redisinsight`
> blocks starts with `#`, including the indented lines.

### Start the service

```bash
make infra-up
```

### Verify

```bash
docker ps --filter name=ere --format "{{.Status}}"
```

The output should show the ERE container as `healthy`. Since ERE has no web
interface, this is the simplest way to confirm it is running.

> **Running without ERE?** If you want to try just ERS and the Webapp without
> the processing engine, add these two lines to ERS's `src/infra/.env`:
>
> ```
> ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET=0
> ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET=0
> ```
>
> ERS will assign temporary identifiers immediately instead of waiting for ERE.
> Restart ERS (`make rebuild`) after changing these values.

---

## Step 4: Start the Webapp

The Webapp provides the user interface for reviewing and curating entity
resolution results. It connects to the Curation API over the shared Docker
network.

### Clone and configure

```bash
git clone https://github.com/OP-TED/entity-resolution-service-webapp.git
cd entity-resolution-service-webapp
cp src/infra/.env.example src/infra/.env
```

The `.env` file has one variable:

| Variable | Default | What it controls |
|----------|---------|------------------|
| `API_BACKEND_URL` | `http://curation-api:8000` | Address of the Curation API |

> The default value uses the Docker container name (`curation-api`) and works
> as-is when the Webapp runs on the `ersys-local` network. Do not change it
> unless you are running the Curation API on a different host.

### Start the service

```bash
make up
```

> **Docker may warn about "orphan containers."** When you run `make up`, Docker
> Compose might report orphan containers (the ERS services running on the same
> network). This is expected — ERS and the Webapp use separate compose files but
> share the `ersys-local` network. You can safely ignore this warning.

### Verify

Open [http://localhost:8080](http://localhost:8080) in a browser. You should
see the ERSys login page.

Log in with the default admin credentials:

- **Email:** `admin@ers.local`
- **Password:** `changeme`

---

## Verify the full stack

With all three components running, confirm everything is connected:

| What to check | How | Expected result |
|---------------|-----|-----------------|
| Curation API | Open `http://localhost:8000/health` | JSON with `"status": "ok"` |
| ERS REST API | Open `http://localhost:8001/health` | JSON with `"status": "ok"` |
| ERE container | Run `docker ps --filter name=ere --format "{{.Status}}"` | Shows `healthy` |
| Webapp | Open `http://localhost:8080` | Login page loads |
| Redis | Run `docker exec ersys-redis redis-cli -a changeme ping` | Shows `PONG` |
| End-to-end | Log in to Webapp → submit an entity mention | The request flows through ERS → Redis → ERE and back |

---

## Configuration reference

Variables that **must match** across repositories for the system to work:

| Variable | ERS `.env` | ERE `.env` | Notes |
|----------|-----------|-----------|-------|
| `REDIS_PASSWORD` | `changeme` | `changeme` | Must be identical in both files |
| `REDIS_HOST` | `ersys-redis` | `ersys-redis` | Docker container name |
| `REDIS_PORT` | `6379` | `6379` | Must be identical in both files |
| `ERSYS_REQUEST_QUEUE` | `ere_requests` (default) | `ere_requests` | Must be identical in both files |
| `ERSYS_RESPONSE_QUEUE` | `ere_responses` (default) | `ere_responses` | Must be identical in both files |

Service ports (defaults — can be changed in each `.env` file):

| Service | Port | Where to change it |
|---------|------|--------------------|
| Curation API | `8000` | ERS `.env` — `UVICORN_PORT` |
| ERS REST API | `8001` | ERS `.env` — `ERS_API_PORT` |
| FerretDB (MongoDB-compatible) | `27017` | ERS compose file |
| Redis | `6379` | ERS compose file |
| Webapp | `8080` | Webapp compose file |

---

## Stopping the stack

Stop services in reverse order — Webapp first, then ERE, then ERS:

```bash
# Webapp
cd entity-resolution-service-webapp
make down

# ERE
cd entity-resolution-engine-basic
make infra-down

# ERS
cd entity-resolution-service
make down
```

### Clean slate (remove all data)

To remove all data and start fresh:

```bash
# Webapp (no persistent data)
cd entity-resolution-service-webapp
make down

# ERE (removes the entity resolution data volume)
cd entity-resolution-engine-basic
make infra-down-volumes

# ERS (removes the database and Redis data volumes)
cd entity-resolution-service
make down-volumes

# Remove the shared network
docker network rm ersys-local
```

---

## Troubleshooting

**Port conflict on 6379** — ERE's built-in Redis is still running. Make sure
you commented out the `ersys-redis` and `redisinsight` services in ERE's
`src/infra/compose.dev.yaml` (see [Step 3](#step-3-start-ere)).

**`ersys-local` network not found** — Create it manually:
`docker network create ersys-local`. This must exist before any `make up`.

**Webapp shows API errors** — Confirm the Curation API is running by opening
`http://localhost:8000/health`. If it works, check that `API_BACKEND_URL` in the
Webapp's `.env` is set to `http://curation-api:8000`.

**ERE processes nothing** — This is normal if no entity mentions have been
submitted. ERE only processes messages when ERS publishes them. Submit an entity
mention through the ERS REST API or the Webapp to trigger resolution.

**Resolution never completes** — Verify ERE is running and connected to the same
Redis instance. Check that `REDIS_PASSWORD` and queue names match between ERS
and ERE `.env` files (see [Configuration reference](#configuration-reference)).