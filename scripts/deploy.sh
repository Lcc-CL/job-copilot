#!/usr/bin/env bash
# Deploy or update Job-Copilot on this host (any Linux + Docker).
#
#   ./scripts/deploy.sh                     # deploy origin/main
#   DEPLOY_REF=<tag|commit> ./scripts/deploy.sh   # deploy a specific version (rollback)
#   SKIP_PULL=1 ./scripts/deploy.sh         # deploy the current checkout as-is
#
# Env file: .env.production (override with ENV_FILE). Database migrations run
# in the container entrypoint on every start. See docs/deployment.md.
#
# The body lives in main() so bash parses it completely before the checkout
# update can rewrite this file mid-run.
set -euo pipefail

main() {
  local root env_file ref timeout
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  cd "$root"

  env_file="${ENV_FILE:-.env.production}"
  ref="${DEPLOY_REF:-main}"
  timeout="${HEALTH_TIMEOUT:-300}"
  local compose=(docker compose -f docker-compose.prod.yml --env-file "$env_file")

  if [[ ! -f "$env_file" ]]; then
    echo "error: $env_file not found — copy .env.production.example and fill it in" >&2
    exit 1
  fi

  if [[ "${SKIP_PULL:-0}" != "1" ]]; then
    echo "==> updating checkout to $ref"
    git fetch --tags origin "$ref"
    git checkout -q --detach FETCH_HEAD
  fi
  echo "==> deploying $(git rev-parse --short HEAD)"

  echo "==> building image"
  "${compose[@]}" build

  echo "==> starting services (entrypoint runs migrations)"
  "${compose[@]}" up -d --remove-orphans

  echo "==> waiting for health (timeout ${timeout}s)"
  local deadline=$((SECONDS + timeout)) cid status
  while :; do
    cid="$("${compose[@]}" ps -q app)"
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || echo missing)"
    [[ "$status" == "healthy" ]] && break
    if (( SECONDS >= deadline )); then
      echo "error: app not healthy (status: $status)" >&2
      "${compose[@]}" logs --tail=50 app >&2
      exit 1
    fi
    sleep 5
  done

  echo "==> deployed $(git rev-parse --short HEAD); app healthy"
}

main "$@"
