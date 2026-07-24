#!/bin/sh
set -eu

echo "[entrypoint] APP_ENV=${APP_ENV:-unknown}"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "[entrypoint] ERROR: DATABASE_URL is not configured" >&2
  exit 1
fi

echo "[entrypoint] Database URL configured: yes"
echo "[entrypoint] Running database migration..."

python -m job_copilot web migrate

echo "[entrypoint] Database migration completed"
echo "[entrypoint] Starting application"

exec uvicorn job_copilot.web:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --log-level info
