# ERSys Black-Box Tests

Black-box tests for the full ERSys stack (ERS + ERE + Webapp).
Tests communicate with running services over HTTP only.

## Quick start

```bash
# 1. Start the full ERSys stack (see docs/testing-ersys.md)
make up

# 2. Point to component repo env files
export ERS_ENV_FILE=/path/to/entity-resolution-service/src/infra/.env
export ERE_ENV_FILE=/path/to/entity-resolution-engine-basic/.env
export WEBAPP_ENV_FILE=/path/to/entity-resolution-service-webapp/.env
# ERS_ENV_FILE defaults to src/infra/.env if not set

# 3. Run
make test-ersys-smoke   # stack reachability (fast)
make test-ersys-e2e     # full e2e suite
make test-ersys-all     # everything
```

## Env files

The tests merge three env files at runtime — later files override earlier ones:

| Env var | Points to | Default |
|---------|-----------|---------|
| `ERS_ENV_FILE` | `src/infra/.env` in the ERS repo | `src/infra/.env` (this repo) |
| `ERE_ENV_FILE` | `.env` in the ERE repo | _(not loaded)_ |
| `WEBAPP_ENV_FILE` | `.env` in the Webapp repo | _(not loaded)_ |

## Full setup guide

See [`docs/testing-ersys.md`](../../docs/testing-ersys.md) for infrastructure
setup, required variables, and debugging tips.
