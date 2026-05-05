# Деплой на Beget VPS

Ниже описан рекомендуемый прод-запуск проекта на Beget VPS через Docker Compose.

## Быстрый старт по IP

Если пока разворачиваем без домена, используйте отдельный IP-конфиг:

- сайт: `http://IP_СЕРВЕРА/`
- API клиента: `http://IP_СЕРВЕРА/api/...`
- админка: `http://IP_СЕРВЕРА/admin/`
- API админки: `http://IP_СЕРВЕРА/api/admin/...`

Файлы для такого режима:

- `deploy/docker-compose.ip.yml`
- `deploy/Caddyfile.ip`
- `deploy/.env.ip.example`
- `deploy/deploy-ip.sh`

Подготовка:

```bash
cp deploy/.env.ip.example deploy/.env.ip
cp backend/.env.production.example backend/.env.production
```

Заполните `deploy/.env.ip`:

```dotenv
SERVER_IP=IP_СЕРВЕРА
NEXT_PUBLIC_API_BASE_URL=http://IP_СЕРВЕРА/api
NEXT_PUBLIC_YANDEX_MAPS_API_KEY=ваш_ключ_яндекс_карт
POSTGRES_DB=postamats
POSTGRES_USER=postamats
POSTGRES_PASSWORD=сложный_пароль
```

Для `backend/.env.production` на IP-режиме минимум:

```dotenv
DEBUG=false

JWT_SECRET_KEY=сложный_секрет
JWT_REFRESH_SECRET_KEY=сложный_секрет_обновления
ADMIN_JWT_SECRET_KEY=сложный_секрет_админки
ADMIN_JWT_REFRESH_SECRET_KEY=сложный_секрет_обновления_админки

WEB_APP_ORIGIN=http://IP_СЕРВЕРА
CORS_ALLOWED_ORIGINS=http://IP_СЕРВЕРА
YOOKASSA_RETURN_URL=http://IP_СЕРВЕРА/payment/return
```

Первый запуск по IP:

```bash
docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml build
docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml run --rm migrate
docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml up -d
```

Или коротко:

```bash
chmod +x deploy/deploy-ip.sh
./deploy/deploy-ip.sh
```

Проверка:

```bash
docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml ps
docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml logs -f caddy web backend
```

## Что будет поднято

- `web` — Next.js сайт на основном домене, например `https://naprokatberu.ru`
- `backend` — FastAPI API и админка на отдельном домене, например `https://api.naprokatberu.ru`
- `db` — PostgreSQL внутри Docker-сети
- `redis` — Redis внутри Docker-сети
- `caddy` — reverse proxy и автоматические SSL-сертификаты Let's Encrypt

Админка будет доступна по адресу `https://api.naprokatberu.ru/admin/`.

## 1. Подготовить DNS

В панели домена направьте A-записи на IP VPS:

- `naprokatberu.ru` -> `IP_СЕРВЕРА`
- `www.naprokatberu.ru` -> `IP_СЕРВЕРА`
- `api.naprokatberu.ru` -> `IP_СЕРВЕРА`

Важно дождаться, пока DNS уже резолвится на VPS, иначе Caddy не сможет сразу выпустить SSL.

## 2. Подключиться к серверу

```bash
ssh root@IP_СЕРВЕРА
```

## 3. Установить Docker на VPS

Для Ubuntu самый быстрый вариант:

```bash
apt update
apt install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker --version
docker compose version
```

## 4. Загрузить проект на сервер

```bash
cd /opt
git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ> postamats
cd /opt/postamats
```

Если репозиторий уже лежит на сервере:

```bash
cd /opt/postamats
git pull
```

## 5. Подготовить env-файлы

Создайте файл для Compose:

```bash
cp deploy/.env.example deploy/.env
```

Откройте `deploy/.env` и заполните:

```dotenv
APP_DOMAIN=naprokatberu.ru
API_DOMAIN=api.naprokatberu.ru
NEXT_PUBLIC_API_BASE_URL=https://api.naprokatberu.ru
NEXT_PUBLIC_YANDEX_MAPS_API_KEY=ваш_ключ_яндекс_карт
POSTGRES_DB=postamats
POSTGRES_USER=postamats
POSTGRES_PASSWORD=сложный_пароль
```

Подготовьте прод-конфиг бэкенда:

```bash
cp backend/.env.production.example backend/.env.production
```

Откройте `backend/.env.production` и заполните минимум:

```dotenv
DEBUG=false

JWT_SECRET_KEY=сложный_секрет
JWT_REFRESH_SECRET_KEY=сложный_секрет_обновления
ADMIN_JWT_SECRET_KEY=сложный_секрет_админки
ADMIN_JWT_REFRESH_SECRET_KEY=сложный_секрет_обновления_админки

WEB_APP_ORIGIN=https://naprokatberu.ru
CORS_ALLOWED_ORIGINS=https://naprokatberu.ru,https://www.naprokatberu.ru
YOOKASSA_RETURN_URL=https://naprokatberu.ru/payment/return

SMS_RU_API_ID=...
SMS_RU_FROM=Naprokat

UPLOAD_DEV_STUB=false
STORAGE_PROVIDER=s3
S3_REGION=ru-1
S3_ENDPOINT_URL=...
S3_FORCE_PATH_STYLE=true
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
S3_PUBLIC_BUCKET=...
S3_PRIVATE_BUCKET=...
MEDIA_PUBLIC_BASE_URL=https://cdn.naprokatberu.ru
```

Примечания:

- `DB_URL`, `ASYNC_DB_URL` и `REDIS_URL` контейнеры получают из `deploy/docker-compose.beget.yml`, поэтому в `backend/.env.production` можно оставить примерные значения или не использовать их как источник истины.
- Если YooKassa и S3 пока не готовы, сайт можно поднять и без них, но соответствующие функции оплаты и загрузки файлов не будут работать.

## 6. Собрать и запустить проект

Первый запуск:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml build
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml run --rm migrate
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml up -d
```

Или коротко:

```bash
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

## 7. Проверить, что все поднялось

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml ps
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml logs -f caddy web backend
```

Проверьте в браузере:

- `https://naprokatberu.ru`
- `https://api.naprokatberu.ru/health`
- `https://api.naprokatberu.ru/admin/`

## 8. Обновление после новых коммитов

```bash
cd /opt/postamats
git pull
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml build
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml run --rm migrate
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml up -d
```

## 9. Если SSL не выпустился

Проверьте:

- домены уже смотрят на VPS
- на сервере открыты порты `80` и `443`
- никакой другой nginx/apache уже не занимает эти порты

Полезно посмотреть логи:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml logs -f caddy
```
