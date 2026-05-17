# Deploy

Репозиторий уже подготовлен под Docker Compose с двумя вариантами:

- `deploy/docker-compose.beget.yml` для домена с `Caddyfile`
- `deploy/docker-compose.ip.yml` для запуска по IP без HTTPS

## Файлы окружения

1. На сервере создайте `deploy/.env` из `deploy/.env.example` для доменного деплоя.
2. Или создайте `deploy/.env.ip` из `deploy/.env.ip.example` для деплоя по IP.
3. Создайте `backend/.env.production` из `backend/.env.production.example`.
4. Для файловых загрузок используется volume `backend_uploads`, поэтому отдельный S3/MinIO не нужен.

Никогда не коммитьте реальные секреты в git.

## Доменный деплой

```bash
cp deploy/.env.example deploy/.env
cp backend/.env.production.example backend/.env.production
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml build
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml run --rm migrate
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml up -d
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml ps
```

## Деплой по IP

```bash
cp deploy/.env.ip.example deploy/.env.ip
cp backend/.env.production.example backend/.env.production
docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml build
docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml run --rm migrate
docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml up -d
docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml ps
```

## Обновление после `git pull`

```bash
git pull origin main
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml build
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml run --rm migrate
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml up -d
```

## Проверка

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml logs -f backend
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml logs -f web
curl http://127.0.0.1:8000/health
```
