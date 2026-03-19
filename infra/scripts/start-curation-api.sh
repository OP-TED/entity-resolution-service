#!/usr/bin/env bash
set -euo pipefail

exec uvicorn ers.curation.entrypoints.api.app:create_app \
    --factory \
    --host "${UVICORN_HOST:-0.0.0.0}" \
    --port "${UVICORN_PORT:-8000}" \
    --workers "${UVICORN_WORKERS:-1}"
