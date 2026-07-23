#!/bin/sh
set -e

echo "[entrypoint] Running database migration..."
python -m job_copilot web migrate

echo "[entrypoint] Starting application on port ${PORT:-8080}..."
exec uvicorn job_copilot.web:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --log-level info
