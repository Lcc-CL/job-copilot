# ---- Stage 1: Frontend Build ----
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# ---- Stage 2: Python Runtime ----
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config/config.example.toml ./config/
COPY .env.example ./
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# /app/data holds the SQLite database when DATABASE_URL is unset; mount a
# volume there so it survives redeploys.
RUN mkdir -p /app/data && useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

ENV PYTHONPATH=/app/src
ENV APP_ENV=production

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/api/health || exit 1

CMD ["./entrypoint.sh"]
