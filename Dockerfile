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

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

ENV PYTHONPATH=/app/src
ENV APP_ENV=production
# Zeabur internal PostgreSQL networking (connect from within cluster)
ENV ZEABUR_PG_HOST=postgresql.zeabur.internal
ENV ZEABUR_PG_USER=root
ENV ZEABUR_PG_PASS=98TrSkJca5Gt6DhXVF0O1P24z3HRU7fY
ENV ZEABUR_PG_DB=zeabur
ENV ZEABUR_PG_PORT=5432

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/api/health || exit 1

CMD ["./entrypoint.sh"]
