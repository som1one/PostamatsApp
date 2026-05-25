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

## Автодеплой из GitHub

Workflow [.github/workflows/deploy.yml](../.github/workflows/deploy.yml)
автоматически деплоит проект на VPS в двух случаях:

- **Push в ветку `main`** — после каждого пуша в `main` запускается
  деплой. Если в момент пуша уже идёт другой деплой, новый ставится в
  очередь (`concurrency: deploy-vps-prod`, `cancel-in-progress: false`),
  чтобы не прерывать миграции.
- **Ручной запуск (`workflow_dispatch`)** — кнопка "Run workflow" на
  странице workflow в GitHub Actions. Независимо от того, какая ветка
  выбрана в "Use workflow from", деплой всегда раскатывает
  `origin/main`.

Что делает workflow:

1. Проверяет, что заданы все секреты (`DEPLOY_HOST`, `DEPLOY_USER`,
   `DEPLOY_PORT`, `DEPLOY_PATH`, `DEPLOY_SSH_KEY`).
2. Кладёт приватный ключ из `DEPLOY_SSH_KEY` в `~/.ssh/deploy_key` на
   runner-е, считывает host key VPS через `ssh-keyscan`.
3. Подключается по SSH, делает `git fetch origin` и
   `git reset --hard origin/main` в `DEPLOY_PATH`.
4. Запускает `bash deploy/deploy-ip.sh`
   (`docker compose build` → `migrate` → `up -d`).
5. Ждёт до 60 секунд, что контейнеры `web` и `backend` перейдут в
   состояние `running`.
6. Удаляет приватный ключ с runner-а.

Volume `backend_uploads` и файлы `deploy/.env.ip`,
`backend/.env.production` на VPS не трогаются — они вне индекса git и
переживают `git reset --hard`.

### Первичная настройка SSH-доступа

1. **Сгенерируй на любой машине ed25519-ключ без passphrase:**

   ```bash
   ssh-keygen -t ed25519 -C "github-actions-deploy" -f ./deploy_key -N ""
   ```

   Это создаст пару `deploy_key` (приватный) и `deploy_key.pub`
   (публичный).

2. **Положи публичную часть в `authorized_keys` на VPS** под тем
   пользователем, под которым будет ходить деплой
   (значение `DEPLOY_USER`):

   ```bash
   ssh <DEPLOY_USER>@<DEPLOY_HOST> -p <DEPLOY_PORT> \
     "mkdir -p ~/.ssh && chmod 700 ~/.ssh && \
      cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys" \
     < ./deploy_key.pub
   ```

3. **Приватную часть** (`deploy_key`) положи в GitHub Secret
   `DEPLOY_SSH_KEY` (см. ниже). В репозиторий приватный ключ
   **не коммить**.

4. **Проверь подключение по ключу:**

   ```bash
   ssh -i ./deploy_key -p <DEPLOY_PORT> <DEPLOY_USER>@<DEPLOY_HOST> \
     "echo ok && cd <DEPLOY_PATH> && git rev-parse HEAD"
   ```

   Критерий успеха: команда отрабатывает без запроса пароля и без
   интерактивных подтверждений, выводит `ok` и хеш текущего HEAD.

### GitHub Secrets и Variables

Добавь параметры в репозитории по пути:
**Settings → Secrets and variables → Actions** → вкладка **Secrets**.

| Имя                | Тип    | Назначение                                              | Пример формата                                             |
|--------------------|--------|---------------------------------------------------------|------------------------------------------------------------|
| `DEPLOY_SSH_KEY`   | Secret | Приватный SSH-ключ для входа на VPS                     | Полный текст ключа в формате OpenSSH (`-----BEGIN OPENSSH PRIVATE KEY-----` … `-----END OPENSSH PRIVATE KEY-----`) |
| `DEPLOY_HOST`      | Secret | IP-адрес или DNS-имя VPS                                | `203.0.113.10` или `vps.example.com`                       |
| `DEPLOY_USER`      | Secret | Системный пользователь на VPS, под которым идёт деплой  | `root` (или `deploy`, если завели отдельного юзера)        |
| `DEPLOY_PORT`      | Secret | SSH-порт VPS                                            | `22`                                                       |
| `DEPLOY_PATH`      | Secret | Абсолютный путь до клонированного репозитория на VPS     | `/opt/postamats`                                           |

Все пять параметров оформлены как Secrets (не Variables), чтобы значения
автоматически маскировались в логах GitHub Actions. Если для какого-то
из параметров маскирование не критично (например, путь), его можно
перенести в Variables — workflow читает оба источника через
`${{ secrets.* }}`/`${{ vars.* }}`.

### Аутентификация только по ключу

Деплой использует **только SSH-ключ**. Пароль пользователя
`DEPLOY_USER` не хранится ни в репозитории, ни в GitHub Secrets, ни в
GitHub Variables и не передаётся через workflow. Если SSH-ключ перестанет
работать — генерируй новый и обновляй `DEPLOY_SSH_KEY` и
`authorized_keys` на VPS, пароль для деплоя не используется.

### Что должно быть на VPS до первого автодеплоя

- Установлены `docker`, плагин `docker compose`, `git`.
- В `DEPLOY_PATH` развёрнут клон репозитория с remote
  `https://github.com/som1one/PostamatsApp` и веткой `main`.
- Лежат заполненные `deploy/.env.ip` и `backend/.env.production`
  (см. соответствующие `*.example`).
- Публичный ключ из `DEPLOY_SSH_KEY` добавлен в
  `~/.ssh/authorized_keys` пользователя `DEPLOY_USER`.
