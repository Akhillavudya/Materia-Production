#!/usr/bin/env sh
# Container entrypoint. Optionally runs DB migrations, then execs the real command
# (uvicorn for the API service, celery for the worker service).
set -e

if [ "${RUN_MIGRATIONS}" = "1" ]; then
  echo "[entrypoint] Applying database migrations (alembic upgrade head)..."
  alembic upgrade head
fi

echo "[entrypoint] Starting: $*"
exec "$@"
