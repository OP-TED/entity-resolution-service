# Infrastructure

Deployment and infrastructure files for the Entity Resolution Service.

## Structure

```
infra/
├── compose.yaml       # Docker Compose service definitions
├── docker/
│   └── Dockerfile     # Multi-stage build (builder + runtime)
└── scripts/
    └── entrypoint.sh  # Container entrypoint
```

## Services

| Service | Purpose | Port |
|---|---|---|
| `api` | ERS FastAPI application | 8000 |
| `ferretdb` | MongoDB-compatible document store | 27017 |
| `postgres` | FerretDB storage backend | — |
| `redis` | ERE contract message queue (ere_requests / ere_responses) | 6379 |

## Usage

All commands run from the repo root via `make`:

```bash
make up        # Start all services
make down      # Stop all services
make rebuild   # Rebuild images and start
make logs      # Follow service logs
```

## Configuration

Environment variables are loaded from `infra/.env`. See `infra/.env.example` for available options. To set up:

```bash
cp infra/.env.example infra/.env
```
