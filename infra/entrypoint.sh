#!/usr/bin/env bash
set -euo pipefail

# --- Dev-only: database seeding ---
if [ "${SEED_DB:-false}" = "true" ]; then
  if python -c "import scripts.seed_db" 2>/dev/null; then
    echo "Seeding DB..."
    python -m scripts.seed_db --mentions 1000 --clusters 15
  else
    echo "Warning: SEED_DB=true but seed script not available (production image)" >&2
  fi
fi

# --- Resolve service to uvicorn module ---
case "${1:-}" in
  curation)
    APP_MODULE="ers.curation.entrypoints.api.app:create_app"
    HOST="${UVICORN_HOST:-0.0.0.0}"
    PORT="${UVICORN_PORT:-8000}"
    WORKERS="${UVICORN_WORKERS:-1}"
    ;;
  ers)
    APP_MODULE="ers.ers_rest_api.entrypoints.api.app:create_app"
    HOST="${ERS_API_UVICORN_HOST:-0.0.0.0}"
    PORT="${ERS_API_PORT:-8001}"
    WORKERS="${ERS_API_UVICORN_WORKERS:-1}"
    ;;
  *)
    echo "Usage: entrypoint.sh {curation|ers}" >&2
    exit 1
    ;;
esac

exec uvicorn "${APP_MODULE}" \
    --factory \
    --host "${HOST}" \
    --port "${PORT}" \
    --workers "${WORKERS}"
