#!/usr/bin/env bash
set -euo pipefail

docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml build
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml run --rm migrate
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml up -d
