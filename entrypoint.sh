#!/bin/sh
set -eu

echo "[entrypoint] APP_ENV=${APP_ENV:-unknown}"

# Zeabur: DATABASE_URL may be unresolved. Check linked service variables directly.
if [ -z "${DATABASE_URL:-}" ]; then
  if [ -n "${POSTGRES_URI:-}" ]; then
    export DATABASE_URL="$POSTGRES_URI"
  elif [ -n "${POSTGRES_CONNECTION_STRING:-}" ]; then
    export DATABASE_URL="$POSTGRES_CONNECTION_STRING"
  fi
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "[entrypoint] ERROR: DATABASE_URL is not configured" >&2
  exit 1
fi

echo "[entrypoint] Database URL configured: yes"

# Wait for database to be ready (up to 90s)
echo "[entrypoint] Waiting for database..."
for i in $(seq 1 30); do
  if python -c "
import os, sys
from sqlalchemy import create_engine, text
try:
    e = create_engine(os.environ['DATABASE_URL'], connect_args={'connect_timeout': 3})
    with e.connect() as c:
        c.execute(text('SELECT 1'))
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    echo "[entrypoint] Database is ready"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "[entrypoint] ERROR: Database not ready after 90s" >&2
    exit 1
  fi
  sleep 3
done

echo "[entrypoint] Running database migration..."
python -m job_copilot web migrate

echo "[entrypoint] Database migration completed"
echo "[entrypoint] Starting application"

exec uvicorn job_copilot.web:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --log-level info
