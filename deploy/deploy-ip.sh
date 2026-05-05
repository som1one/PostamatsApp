#!/usr/bin/env bash
set -euo pipefail

docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml build
docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml run --rm migrate
docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml up -d

