# Infrastructure

Deployment and infrastructure files for the Entity Resolution Service.

## Structure

```
infra/
├── .env.example      # Environment variable template
├── compose.yaml      # Docker Compose service definitions
├── Dockerfile        # Multi-stage build (ARG ENVIRONMENT=production|development)
├── entrypoint.sh     # Container entrypoint (seeding + service start)
└── README.md
```

## Services

| Service | Purpose | Port |
|---|---|---|
| `curation-api` | Curation FastAPI application | 8000 |
| `ers-api` | ERS FastAPI application | 8001 |
| `ferretdb` | MongoDB-compatible document store | 27017 |
| `postgres` | FerretDB storage backend (DocumentDB) | — (internal) |
| `redis` | ERE contract message queue | 6379 |

## Usage

All commands run from the repo root via `make`:

```bash
make up              # Start all services
make down            # Stop all services
make down-volumes    # Stop services and remove volumes (clean slate)
make rebuild         # Rebuild images and start
make rebuild-clean   # Rebuild from scratch (no cache)
make logs            # Follow service logs
make watch           # Start services with file watching (hot-reload)
```

### File watching (development)

`make watch` uses Docker Compose's `watch` feature to sync source code changes
into running containers without a full rebuild:

- **Source changes** (`src/`) are synced live into the container.
- **Dependency changes** (`pyproject.toml`, `poetry.lock`) trigger a full rebuild.

### Production build

The Dockerfile defaults to a production build. To build manually:

```bash
docker build -f infra/Dockerfile -t ers:latest .
```

The development build (used by `make up`) includes dev dependencies, tests, and project scripts:

```bash
docker build -f infra/Dockerfile --build-arg ENVIRONMENT=development -t ers:dev .
```

## Configuration

Environment variables are loaded from `infra/.env`. See `infra/.env.example` for available options. To set up:

```bash
cp infra/.env.example infra/.env
```
