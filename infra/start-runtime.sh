#!/bin/sh
set -eu

ROLE="${BLOCKVAULT_RUNTIME_ROLE:-api}"

if [ "$ROLE" = "worker" ]; then
  exec python -m blockvault_worker.main
fi

PORT_VALUE="${PORT:-8000}"

exec gunicorn \
  -k uvicorn.workers.UvicornWorker \
  -w "${BLOCKVAULT_GUNICORN_WORKERS:-2}" \
  -b "0.0.0.0:${PORT_VALUE}" \
  --chdir /app/apps/api/src \
  blockvault_api.main:app
