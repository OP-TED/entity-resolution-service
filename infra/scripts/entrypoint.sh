#!/usr/bin/env bash
set -euo pipefail

if [ "${SEED_DB:-false}" = "true" ]; then
  echo "Seeding DB..."
  python -m scripts.seed_db --mentions 1000 --clusters 15
fi

exec "$@"
