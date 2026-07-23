#!/bin/sh
set -e

# Auto-detect DATABASE_URL from Zeabur PostgreSQL service variables
if [ -z "$DATABASE_URL" ]; then
  # Try common Zeabur PostgreSQL variable names
  for var in POSTGRES_CONNECTION_STRING POSTGRES_URI DATABASE_URL_REF NEON_DATABASE_URL; do
    eval "val=\${$var}"
    if [ -n "$val" ]; then
      export DATABASE_URL="$val"
      echo "[entrypoint] Using DATABASE_URL from \$$var"
      break
    fi
  done
fi

echo "[entrypoint] Running database migration..."
python -m job_copilot web migrate

echo "[entrypoint] Starting application on port ${PORT:-8080}..."
exec uvicorn job_copilot.web:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --log-level info
