#!/usr/bin/env bash
set -euo pipefail

# Доменный деплой: Caddy с HTTPS (Let's Encrypt) + web + backend + db + redis.
# Используется автодеплоем (.github/workflows/deploy.yml) и при ручных
# обновлениях. Все параметры (APP_DOMAIN, креды Postgres, Yandex Maps API key)
# берутся из deploy/.env, секреты бэкенда — из backend/.env.production.

# Ингрешн опциональных секретов из окружения деплоя в backend/.env.production.
# Это нужно, чтобы не возить секреты руками по SSH — autodeploy подкладывает
# их из GitHub Secrets в env workflow, а здесь мы аккуратно их апсёртим.
# Не трогаем строки, если переменная окружения пустая.
inject_env_var() {
  local key="$1"
  local value="${2-}"
  local file="backend/.env.production"
  if [ -z "${value}" ]; then
    return 0
  fi
  if [ ! -f "${file}" ]; then
    echo "[deploy] WARNING: ${file} is missing, cannot inject ${key}" >&2
    return 0
  fi
  # Удаляем существующую строку с этим ключом (если была) и добавляем заново.
  # sed -i работает на linux runner-е и на VPS (gnu sed).
  sed -i "/^${key}=/d" "${file}"
  printf '%s=%s\n' "${key}" "${value}" >> "${file}"
  echo "[deploy] injected ${key} into ${file}"
}

inject_env_var "TELEGRAM_ADMIN_BOT_TOKEN" "${TELEGRAM_ADMIN_BOT_TOKEN-}"
inject_env_var "TELEGRAM_API_TIMEOUT_SECONDS" "${TELEGRAM_API_TIMEOUT_SECONDS-}"
inject_env_var "TELEGRAM_WEBHOOK_SECRET" "${TELEGRAM_WEBHOOK_SECRET-}"
inject_env_var "ADMIN_PANEL_URL" "${ADMIN_PANEL_URL-}"

COMPOSE_ARGS=(--env-file deploy/.env -f deploy/docker-compose.beget.yml)

docker compose "${COMPOSE_ARGS[@]}" build
docker compose "${COMPOSE_ARGS[@]}" run --rm migrate
docker compose "${COMPOSE_ARGS[@]}" up -d

# Разовая миграция постаматов в боевую конфигурацию.
# Скрипт идемпотентный: повторные деплои просто приводят каждую точку
# к целевому состоянию (Невский — фейковый seed/OFFLINE, Петроградка
# удаляется, ВН Центр — настоящий ESI 0980, ВН Запад — seed/OFFLINE).
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
  echo "[deploy] running scripts.migrate_lockers_to_real (idempotent)"
  docker compose "${COMPOSE_ARGS[@]}" exec -T backend \
    python -m scripts.migrate_lockers_to_real

  # echo "[deploy] running scripts.fix_manual_products (updating images)"
  # docker compose "${COMPOSE_ARGS[@]}" exec -T backend \
  #   python -m scripts.fix_manual_products
else
  echo "[deploy] WARNING: backend container did not reach running state, skipping locker migration" >&2
fi
