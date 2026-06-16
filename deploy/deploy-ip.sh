#!/usr/bin/env bash
set -euo pipefail

COMPOSE_ARGS=(--env-file deploy/.env.ip -f deploy/docker-compose.ip.yml)

docker compose "${COMPOSE_ARGS[@]}" build
docker compose "${COMPOSE_ARGS[@]}" run --rm migrate
docker compose "${COMPOSE_ARGS[@]}" up -d

# Разовая миграция постаматов в боевую конфигурацию.
# Скрипт идемпотентный: повторные деплои просто проверяют, что
# каждая точка уже в нужном состоянии. Если в будущем понадобится
# выключить — достаточно убрать этот блок.
echo "[deploy] waiting for backend container to become running"
deadline=$(( $(date +%s) + 60 ))
backend_ready=0
while :; do
  backend_id=$(docker compose "${COMPOSE_ARGS[@]}" ps -q backend 2>/dev/null || true)
  if [ -n "${backend_id}" ]; then
    backend_state=$(docker inspect -f '{{.State.Status}}' "${backend_id}" 2>/dev/null || echo "missing")
    if [ "${backend_state}" = "running" ]; then
      backend_ready=1
      break
    fi
  fi
  if [ "$(date +%s)" -ge "${deadline}" ]; then
    break
  fi
  sleep 2
done

if [ "${backend_ready}" -eq 1 ]; then
  echo "[deploy] applying catalog bundle (idempotent)"
  docker compose "${COMPOSE_ARGS[@]}" exec -T backend \
    python -m scripts.apply_catalog_bundle \
      --bundle /app/deploy/catalog-sync.bundle.json \
      --apply --force

  echo "[deploy] running scripts.migrate_lockers_to_real (idempotent)"
  docker compose "${COMPOSE_ARGS[@]}" exec -T backend \
    python -m scripts.migrate_lockers_to_real
else
  echo "[deploy] WARNING: backend container did not reach running state, skipping locker migration and catalog sync" >&2
fi
