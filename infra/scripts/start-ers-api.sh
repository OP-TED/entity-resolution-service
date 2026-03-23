#!/usr/bin/env bash
set -euo pipefail

exec uvicorn ers.ers_rest_api.entrypoints.api.app:create_app \
    --factory \
    --host "${ERS_API_UVICORN_HOST:-0.0.0.0}" \
    --port "${ERS_API_PORT:-8001}" \
    --workers "${ERS_API_UVICORN_WORKERS:-1}"
