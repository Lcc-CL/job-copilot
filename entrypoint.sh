#!/bin/sh
set -eu

echo "[entrypoint] APP_ENV=${APP_ENV:-unknown}"

# Database: DATABASE_URL (PostgreSQL) when set; otherwise SQLite under
# /app/data (mount a volume there so it survives redeploys).
if [ -n "${DATABASE_URL:-}" ]; then
  echo "[entrypoint] Database: DATABASE_URL"
  # Wait for the database to be ready (up to 90s)
  echo "[entrypoint] Waiting for database..."
  for i in $(seq 1 30); do
    result=$(python -c "
from sqlalchemy import create_engine, text
from job_copilot.database import _get_database_url
try:
    url = _get_database_url()
    args = {'connect_timeout': 3} if url.startswith('postgresql') else {}
    e = create_engine(url, connect_args=args)
    with e.connect() as c:
        c.execute(text('SELECT 1'))
    print('OK')
except Exception as ex:
    print(type(ex).__name__)
" 2>/dev/null)
    if [ "$result" = "OK" ]; then
      echo "[entrypoint] Database is ready"
      break
    fi
    if [ -n "$result" ]; then
      echo "[entrypoint] DB attempt $i/30: $result"
    fi
    if [ "$i" -eq 30 ]; then
      echo "[entrypoint] ERROR: Database not ready after 90s" >&2
      exit 1
    fi
    sleep 3
  done
else
  echo "[entrypoint] Database: SQLite (data/jobcopilot.db; DATABASE_URL not set)"
fi

echo "[entrypoint] Running database migration..."
python -m job_copilot web migrate

echo "[entrypoint] Database migration completed"
echo "[entrypoint] Starting application"

# Behind a reverse proxy, set FORWARDED_ALLOW_IPS to the proxy's address so
# uvicorn trusts its X-Forwarded-For (used by the per-IP login limiter).
exec uvicorn job_copilot.web:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --log-level info
