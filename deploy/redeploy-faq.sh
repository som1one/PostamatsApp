#!/usr/bin/env bash
# Применяет на проде новый список FAQ (web/src/shared/content.ts).
#
# Поскольку FAQ хранятся как статический модуль на фронте, для смены контента
# достаточно подтянуть код и пересобрать только web-контейнер. Бэкенд и БД не
# трогаются — таблиц с FAQ в базе нет.
#
# Запуск (на сервере, в /opt/postamats):
#   chmod +x deploy/redeploy-faq.sh
#   ./deploy/redeploy-faq.sh
#
# По умолчанию работает с .env.ip / docker-compose.ip.yml. Если продовый
# конфиг другой — переопределите переменные:
#   ENV_FILE=deploy/.env COMPOSE_FILE=deploy/docker-compose.beget.yml \
#     ./deploy/redeploy-faq.sh
set -euo pipefail

ENV_FILE="${ENV_FILE:-deploy/.env.ip}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.ip.yml}"
BRANCH="${BRANCH:-codex/deploy-ip-vps}"

echo "==> Подтягиваем свежий код из ветки ${BRANCH}"
git fetch origin "${BRANCH}"
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"

echo "==> Пересобираем web-контейнер"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build web

echo "==> Поднимаем web-контейнер"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d web

echo "==> Готово. Проверьте /faq на прод-домене."
