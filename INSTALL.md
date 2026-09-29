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

> **Rebuilding with a clean cache:** If you have upgraded the source or made changes to
> the Docker image and need to discard cached layers, run:
> ```bash
> make rebuild-clean
> ```

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

> **Deploying onto an existing database?** If v1.1.0 is being deployed over an
> existing database (not a fresh install), run the
> [operational scripts](#operational-scripts) after the services are healthy to
> backfill projections introduced in this release.

---

## Running ERS in multi-node mode

This section is independent of the step-by-step guide above. It describes how
to run multiple replicas of `curation-api` and `ers-api` behind a load balancer
for horizontal scaling or high availability. You can apply this pattern whether
you are running ERS standalone or as part of the full ERSys stack.

### How cross-replica coordination works

Each ERS API instance subscribes to a Redis pub/sub channel at startup. When one
replica completes a resolution request, it publishes the result on that channel
so that all other replicas — including the one that is holding the HTTP
connection open for the client — can pick it up. Without this mechanism, a
request routed to replica A could be answered by replica B's ERE response, and
replica A would never see it.

This means two things must be true before a replica starts accepting traffic:

1. Redis must be reachable.
2. The pub/sub subscription must be established.

The `ERS_SUBSCRIBER_READY_TIMEOUT` variable enforces point 2 — the replica
waits up to that many seconds for the subscription handshake to complete before
the process is considered ready. If you set it to `0`, the gate is disabled and
the load balancer may route requests before the channel is up (not recommended).

### Environment variables for multi-replica deployments

All three variables have safe defaults and do not need to be set explicitly
unless you want to override them. Set them on every `curation-api` and `ers-api`
replica, and ensure the values are identical across all replicas.

| Variable | Default | Purpose |
|----------|---------|---------|
| `ERS_NOTIFICATIONS_CHANNEL` | `ers_notifications` | Redis pub/sub channel for cross-replica notifications. Coordinates delivery of an ERE response to the replica that originated the request. |
| `ERS_SUBSCRIBER_READY_TIMEOUT` | `5.0` | Seconds to wait for the pub/sub subscription to be established at startup. Set to `0` to disable (not recommended in multi-replica deployments). |
| `REDIS_SOCKET_CONNECT_TIMEOUT` | `5.0` | Seconds to wait for the TCP handshake when connecting to Redis. Applies to all Redis connections. Prevents indefinite blocking if Redis is unreachable. |

### Worker count

In a multi-replica deployment, set `UVICORN_WORKERS=1` on each container and
let the load balancer distribute traffic across replicas. Running multiple
Uvicorn workers per container alongside a load balancer complicates instance
identity and offers no benefit over adding more replicas.

### Database seeding

**Set `SEED_DB=false` on every replica.** If multiple replicas start with
`SEED_DB=true`, each one will attempt to seed the database concurrently, which
causes conflicts and duplicate data.

The correct pattern is a dedicated one-shot seed container that runs once before
the API replicas start, completes successfully, and exits. The API replicas then
start only after the seed container has finished. In a `compose.override.yaml`
this looks like:

```yaml
seed:
  build:
    context: .
    dockerfile: src/infra/Dockerfile
    args:
      ENVIRONMENT: development
  entrypoint: ["python", "/app/scripts/seed_db.py"]
  restart: no
  depends_on:
    ferretdb:
      condition: service_healthy

curation-api:
  environment:
    SEED_DB: "false"
  depends_on:
    seed:
      condition: service_completed_successfully
```

### Load balancer configuration

ERS does not include a load balancer — you bring your own. Both `curation-api`
(port 8000) and `ers-api` (port 8001) are stateless HTTP services and work with
any HTTP load balancer. The following are examples of one possible way to
configure a load balancer — adapt them to your own setup.

Place your load balancer configuration in a `compose.override.yaml` file
alongside `src/infra/compose.dev.yaml`. Docker Compose merges override files
automatically when you run `docker compose up`, so you do not need to pass `-f`
flags. In the override file, remove the host port mappings from the API services
and let the load balancer own those ports instead.

#### Traefik

Traefik must be attached to the same Docker network as the API containers
(`ersys-local`). Add these to your `compose.override.yaml`:

```yaml
services:
  traefik:
    image: traefik:v3.7
    command:
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--providers.docker.network=ersys-local"
      - "--entrypoints.curation.address=:8000"
      - "--entrypoints.ers.address=:8001"
    ports:
      - "8000:8000"
      - "8001:8001"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - ersys-local

  curation-api:
    container_name: !reset null
    ports: !reset []
    deploy:
      replicas: 2
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.curation.entrypoints=curation"
      - "traefik.http.routers.curation.rule=PathPrefix(`/`)"
      - "traefik.http.services.curation.loadbalancer.server.port=8000"

  ers-api:
    container_name: !reset null
    ports: !reset []
    deploy:
      replicas: 2
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.ers.entrypoints=ers"
      - "traefik.http.routers.ers.rule=PathPrefix(`/`)"
      - "traefik.http.services.ers.loadbalancer.server.port=8001"
```

See the [Traefik Docker provider docs](https://doc.traefik.io/traefik/providers/docker/)
for the full Traefik setup.

#### nginx

nginx is not included in the ERSys stack; the snippet below assumes you are
running nginx as a separate container or service on the same Docker network as
the API containers.

nginx must be able to resolve the container names of your replicas. Since Docker
Compose does not assign predictable names to scaled containers, use the service
DNS name (e.g. `curation-api`) and let Docker's internal DNS round-robin across
replicas, or assign explicit container names per replica.

Define an upstream block for each API in your nginx configuration:

```nginx
upstream curation_api {
    server curation-api-1:8000;
    server curation-api-2:8000;
}

upstream ers_api {
    server ers-api-1:8001;
    server ers-api-2:8001;
}

server {
    listen 8000;
    location / {
        proxy_pass http://curation_api;
    }
}

server {
    listen 8001;
    location / {
        proxy_pass http://ers_api;
    }
}
```

Replace `curation-api-1`, `curation-api-2`, etc. with the actual container
names or DNS names of your replicas. See the
[nginx upstream docs](https://nginx.org/en/docs/http/ngx_http_upstream_module.html)
for the full configuration reference.

### Verify

Once the stack is running with multiple replicas, confirm everything is working:

```bash
# Health endpoints — both should return {"status": "ok"}
curl http://localhost:8000/health    # Curation API (via load balancer)
curl http://localhost:8001/health    # ERS REST API (via load balancer)

# Confirm multiple replicas are running
docker ps --filter name=curation-api --format "{{.Names}}\t{{.Status}}"
docker ps --filter name=ers-api --format "{{.Names}}\t{{.Status}}"
```

You should see two (or more) containers listed for each API service, all with
status `healthy` or `Up`.

To confirm the load balancer is distributing traffic, check its logs:

```bash
# Traefik
docker logs ersys-traefik

# nginx (adjust container name as needed)
docker logs ersys-nginx
```

Look for requests being routed to different upstream containers across successive
calls.

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

> **Rebuilding with a clean cache:** To force a full rebuild of the ERE Docker image
> without cached layers, run instead:
> ```bash
> make infra-rebuild-clean
> ```

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
| `API_BACKEND_URL` | `curation-api:8000` | Address of the Curation API (host and port only — no protocol prefix) |

> The default value uses the Docker container name (`curation-api`) and works
> as-is when the Webapp runs on the `ersys-local` network. The value must be
> `host:port` only — without a protocol prefix. 

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

## Operational scripts

These scripts backfill and verify projections introduced in v1.1.0. They are
idempotent — safe to re-run. On a fresh (empty) database the live service
maintains these projections automatically; the scripts are only needed when
deploying onto an existing database or repairing drift.

**Run order: backfills first, then verify.**

### Rebuild the `cluster_sizes` projection

```bash
# Preview (no writes):
cd src && poetry run python -m scripts.backfill_cluster_sizes --dry-run

# Apply:
make backfill-cluster-sizes
```

**When to run:** after the initial deployment of v1.1.0 onto an existing
database (the projection starts empty), after any data migration that moves
decisions between clusters, or whenever `make verify-cluster-sizes` reports
drift.

> **Live-system warning:** this script uses `$set` (absolute overwrite). If run
> while decisions are actively being integrated, a concurrent `$inc` write from
> the integrator can be lost. Run during a maintenance window or quiet period.

### Seed review-state fields on existing decisions

```bash
# Preview:
cd src && poetry run python -m scripts.backfill_previous_review_count --dry-run

# Apply:
make backfill-review-counts
```

Sets two fields on each decision that has recorded user actions:
`previous_review_count` (total action count) and `reviewed_since_placement`
(`true` if the latest action post-dates the current placement boundary).

**When to run:** once, after the initial deployment of v1.1.0 onto an existing
database, for decisions curated before these fields were introduced.

### Verify the `cluster_sizes` projection

```bash
make verify-cluster-sizes
# or: cd src && poetry run python -m scripts.verify_cluster_sizes --verbose
```

Exits `0` if consistent, `1` if drift detected (logs each discrepancy). Run
after either backfill to confirm the projection is clean, or as a periodic
health check.

**Repair loop — what to do when drift is detected:**

```bash
# 1. Confirm the drift and review the log output
make verify-cluster-sizes

# 2. Preview what the repair will write or delete
cd src && poetry run python -m scripts.backfill_cluster_sizes --dry-run

# 3. Run during a maintenance window or quiet period (see live-system warning above)
make backfill-cluster-sizes

# 4. Confirm the projection is clean
make verify-cluster-sizes   # should exit 0
```

If step 4 still reports drift, a concurrent write raced with the backfill —
wait for the system to quiesce and repeat from step 2.

> **`--batch-size` note:** controls write-batch size in the backfill scripts,
> not the read chunk size. The full aggregation is loaded into memory before
> writes begin.

---

## Troubleshooting

**Port conflict on 6379** — ERE's built-in Redis is still running. Make sure
you commented out the `ersys-redis` and `redisinsight` services in ERE's
`src/infra/compose.dev.yaml` (see [Step 3](#step-3-start-ere)).

**`ersys-local` network not found** — Create it manually:
`docker network create ersys-local`. This must exist before any `make up`.

**Webapp shows API errors** — Confirm the Curation API is running by opening
`http://localhost:8000/health`. If it works, check that `API_BACKEND_URL` in the
Webapp's `.env` is set to `curation-api:8000` (host and port only, no `http://`
prefix — Nginx adds the protocol when proxying requests).

**ERE processes nothing** — This is normal if no entity mentions have been
submitted. ERE only processes messages when ERS publishes them. Submit an entity
mention through the ERS REST API or the Webapp to trigger resolution.

**Resolution never completes** — Verify ERE is running and connected to the same
Redis instance. Check that `REDIS_PASSWORD` and queue names match between ERS
and ERE `.env` files (see [Configuration reference](#configuration-reference)).

**Entity schema changes cause errors** — If you have modified the entity type
configuration (`src/config/rdf_mention_config.yaml`) and the database was already
initialised with the previous schema, you may see errors on startup or during
request processing. Remove the data volumes and restart to start fresh:

```bash
make down-volumes   # stop services and delete all data volumes
make up
```

All previously ingested data will be lost. This is expected when the schema changes.