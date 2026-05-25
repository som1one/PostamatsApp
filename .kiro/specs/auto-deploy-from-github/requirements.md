# Requirements Document

## Introduction

Эта спека описывает требования к автоматическому деплою проекта PostamatsApp
из репозитория GitHub (`som1one/PostamatsApp`) на VPS-сервер по IP без HTTPS.

Цель — заменить ручной запуск `deploy/deploy-ip.sh` на сервере на
автоматический процесс, который запускается при пуше в ветку `main` и при
ручном вызове через GitHub Actions UI. Workflow подключается к серверу по
SSH с приватным ключом из GitHub Secrets, обновляет рабочую копию
(`git fetch` + `git reset --hard origin/main`) и переиспользует
существующий `deploy/deploy-ip.sh` (`docker compose build` → `migrate` →
`up -d`). Параллельные запуски сериализуются через `concurrency`, ошибка
любого шага приводит к failed-статусу workflow с понятным логом.

Реализация затрагивает только три артефакта:

- `.github/workflows/deploy.yml` — GitHub Actions workflow;
- раздел в `deploy/README.md` про автодеплой и первичную настройку SSH;
- (опционально) обёртка над `deploy/deploy-ip.sh`, если потребуется
  отдельный entrypoint для CI.

Существующий volume `backend_uploads`, файлы `deploy/.env.ip` и
`backend/.env.production` на сервере деплой НЕ перезаписывает.

## Glossary

- **Repository**: репозиторий `som1one/PostamatsApp` на GitHub.
- **VPS**: целевой сервер деплоя, доступный по IP, путь к проекту хранится
  в GitHub Variables (по умолчанию `/opt/postamats`).
- **Deploy_Workflow**: GitHub Actions workflow в файле
  `.github/workflows/deploy.yml`.
- **Deploy_Script**: существующий shell-скрипт `deploy/deploy-ip.sh`,
  выполняющий `docker compose build` → `migrate` → `up -d` с
  `--env-file deploy/.env.ip` и `-f deploy/docker-compose.ip.yml`.
- **Deploy_Job**: задача (job) внутри Deploy_Workflow, выполняющаяся на
  `ubuntu-latest` и подключающаяся по SSH к VPS.
- **SSH_Key**: приватный SSH-ключ ed25519, хранится только в GitHub
  Secrets (имя секрета — `DEPLOY_SSH_KEY`).
- **Deploy_Secrets**: набор GitHub Secrets и Variables, описывающих
  доступ к VPS: `DEPLOY_SSH_KEY` (secret), `DEPLOY_HOST`, `DEPLOY_USER`,
  `DEPLOY_PORT`, `DEPLOY_PATH` (могут быть Secrets или Variables, но
  никогда не хардкодятся в коде workflow).
- **Backend_Uploads_Volume**: docker volume `backend_uploads`,
  объявленный в `deploy/docker-compose.ip.yml`, в котором хранятся
  пользовательские файлы.
- **Production_Env_Files**: файлы окружения на сервере —
  `deploy/.env.ip` и `backend/.env.production`. Создаются вручную и в
  репозиторий не коммитятся.
- **Deployment**: один полный прогон Deploy_Job: подключение по SSH,
  обновление рабочей копии, запуск Deploy_Script.

## Requirements

### Requirement 1: Автоматический деплой при пуше в main

**User Story:** Как разработчик, я хочу, чтобы любой пуш в ветку `main`
автоматически выкатывался на VPS, так чтобы prod был синхронен с `main`
без ручных команд на сервере.

#### Acceptance Criteria

1. WHEN коммит пушится в ветку `main` Repository, THE Deploy_Workflow
   SHALL запуститься автоматически на runner-е `ubuntu-latest`.
2. WHEN Deploy_Workflow стартует по push в `main`, THE Deploy_Job SHALL
   подключиться к VPS по SSH, используя `DEPLOY_HOST`, `DEPLOY_USER`,
   `DEPLOY_PORT` и `SSH_Key` из Deploy_Secrets.
3. WHEN SSH-сессия с VPS установлена, THE Deploy_Job SHALL перейти в
   директорию `DEPLOY_PATH`, выполнить `git fetch origin` и
   `git reset --hard origin/main`, после чего запустить Deploy_Script.
4. WHEN Deploy_Script завершился с кодом 0, THE Deploy_Workflow SHALL
   завершиться со статусом `success`.

### Requirement 2: Ручной запуск деплоя через workflow_dispatch

**User Story:** Как разработчик, я хочу запускать деплой вручную из UI
GitHub Actions без пуша новых коммитов, так чтобы переразвернуть
текущий `main` (например, после правки секрета на сервере).

#### Acceptance Criteria

1. THE Deploy_Workflow SHALL поддерживать триггер `workflow_dispatch`.
2. WHEN пользователь запускает Deploy_Workflow вручную через
   `workflow_dispatch`, THE Deploy_Workflow SHALL выполнить тот же
   сценарий деплоя, что и при push в `main` (Requirement 1, criteria 2–4).

### Requirement 3: Сериализация параллельных деплоев

**User Story:** Как разработчик, я хочу, чтобы два деплоя не выполнялись
одновременно на одном сервере, так чтобы избежать гонок при `git reset`,
билде образов и применении миграций.

#### Acceptance Criteria

1. THE Deploy_Workflow SHALL объявлять группу `concurrency` с ключом,
   общим для всех запусков деплоя на VPS (например,
   `deploy-ip-${{ github.ref }}` или фиксированное имя).
2. WHEN Deploy_Workflow уже выполняется и приходит новый push в `main`
   или новый `workflow_dispatch`, THE Deploy_Workflow SHALL дождаться
   завершения текущего Deployment либо отменить предыдущий запуск через
   `cancel-in-progress`, не допуская одновременного выполнения двух
   Deploy_Job на VPS.

### Requirement 4: Падение деплой-скрипта на сервере

**User Story:** Как разработчик, я хочу, чтобы при падении любого шага
деплоя (build, migrate, up) workflow помечался как failed и в логах было
видно, что именно упало, так чтобы починить проблему по логам.

#### Acceptance Criteria

1. IF любая команда внутри Deploy_Script (`docker compose build`,
   `migrate`, `up -d`) завершилась с кодом, отличным от 0, THEN THE
   Deploy_Job SHALL завершиться с ненулевым кодом возврата.
2. IF Deploy_Job завершился с ненулевым кодом возврата, THEN THE
   Deploy_Workflow SHALL завершиться со статусом `failure`.
3. IF Deployment упал, THEN THE Deploy_Workflow SHALL НЕ выполнять
   автоматический откат коммита в Repository и НЕ откатывать состояние
   контейнеров на VPS.

### Requirement 5: Видимость логов деплоя в GitHub Actions

**User Story:** Как разработчик, я хочу видеть полный stdout/stderr
деплой-скрипта прямо в логах GitHub Actions, так чтобы не ходить на
сервер за логами при каждой ошибке.

#### Acceptance Criteria

1. WHEN Deploy_Job выполняет команды по SSH на VPS, THE Deploy_Job
   SHALL стримить stdout и stderr этих команд в лог GitHub Actions.
2. WHEN Deploy_Script печатает строку в stdout или stderr, THE
   Deploy_Workflow SHALL отображать эту строку в логе шага не позднее
   завершения Deploy_Job.

### Requirement 6: Обработка ошибок SSH-подключения

**User Story:** Как разработчик, я хочу получать понятную ошибку, если
SSH-ключ невалидный или сервер недоступен, так чтобы быстро понять,
что проблема в инфраструктуре, а не в коде.

#### Acceptance Criteria

1. IF SSH-подключение к `DEPLOY_HOST:DEPLOY_PORT` не устанавливается в
   течение 60 секунд, THEN THE Deploy_Job SHALL завершиться с ненулевым
   кодом возврата и сообщением, содержащим причину (timeout, refused,
   unknown host).
2. IF `SSH_Key` из Deploy_Secrets отвергнут сервером (permission
   denied), THEN THE Deploy_Job SHALL завершиться с ненулевым кодом
   возврата и сообщением `Permission denied (publickey)` или эквивалентным.
3. IF Deploy_Job упал из-за SSH-ошибки, THEN THE Deploy_Job SHALL НЕ
   выполнять `git reset` и Deploy_Script на VPS.

### Requirement 7: Хранение секретов только в GitHub Secrets/Variables

**User Story:** Как разработчик, я хочу, чтобы SSH-ключ, IP сервера,
пользователь, порт и путь к проекту никогда не попадали в репозиторий,
так чтобы доступ к VPS не утёк через git-историю.

#### Acceptance Criteria

1. THE Deploy_Workflow SHALL читать `SSH_Key` исключительно из GitHub
   Secret `DEPLOY_SSH_KEY`.
2. THE Deploy_Workflow SHALL читать `DEPLOY_HOST`, `DEPLOY_USER`,
   `DEPLOY_PORT`, `DEPLOY_PATH` исключительно из GitHub Secrets или
   GitHub Variables (на усмотрение реализации), и НЕ хардкодить эти
   значения в `.github/workflows/deploy.yml`.
3. THE Repository SHALL НЕ содержать файлов `deploy/.env.ip`,
   `backend/.env.production`, приватных SSH-ключей и пароля от VPS.
4. WHEN Deploy_Workflow логирует команды, THE Deploy_Workflow SHALL
   маскировать значения Deploy_Secrets в логах (стандартное поведение
   GitHub Actions при использовании `secrets.*`).

### Requirement 8: Сохранность данных и env-файлов на сервере

**User Story:** Как разработчик, я хочу, чтобы автодеплой не терял
загруженные файлы и не перезаписывал ручные `.env`-файлы на сервере,
так чтобы пользовательские данные и секреты переживали любой деплой.

#### Acceptance Criteria

1. WHEN Deployment выполняется, THE Deploy_Job SHALL сохранять docker
   volume `Backend_Uploads_Volume` неизменным (не удалять и не
   пересоздавать).
2. WHEN Deploy_Job выполняет `git reset --hard origin/main` в
   `DEPLOY_PATH`, THE Deploy_Job SHALL НЕ удалять и не перезаписывать
   `deploy/.env.ip` и `backend/.env.production` на VPS (эти файлы
   находятся вне индекса git и должны переживать `git reset`).
3. IF Deployment завершился со статусом `success`, THEN THE
   Backend_Uploads_Volume SHALL содержать те же файлы, что и до запуска
   Deployment.

### Requirement 9: Состояние контейнеров после успешного деплоя

**User Story:** Как разработчик, я хочу, чтобы после зелёного workflow
контейнеры `web` и `backend` были запущены, а миграции применены, так
чтобы зелёный билд означал работающий prod.

#### Acceptance Criteria

1. WHEN Deploy_Script выполняется, THE Deploy_Job SHALL запустить
   alembic-миграции через сервис `migrate` из
   `deploy/docker-compose.ip.yml` до старта основных сервисов.
2. WHEN Deployment завершился со статусом `success`, THE сервисы `web`
   и `backend` из `deploy/docker-compose.ip.yml` SHALL находиться в
   состоянии `running` на VPS.
3. IF сервис `migrate` завершился с ненулевым кодом, THEN THE
   Deploy_Job SHALL завершиться с ненулевым кодом возврата и НЕ
   помечать Deployment как успешный (см. Requirement 4).

### Requirement 10: Документация по первичной настройке

**User Story:** Как новый член команды, я хочу прочитать в
`deploy/README.md`, как сгенерировать SSH-ключ, положить публичную часть
на сервер и настроить GitHub Secrets, так чтобы поднять автодеплой с
нуля без догадок.

#### Acceptance Criteria

1. THE `deploy/README.md` SHALL содержать раздел про автодеплой из
   GitHub, описывающий триггеры (`push` в `main` и `workflow_dispatch`),
   и ссылающийся на `.github/workflows/deploy.yml`.
2. THE `deploy/README.md` SHALL содержать инструкцию по генерации
   SSH-ключа ed25519 (команда `ssh-keygen -t ed25519`), размещению
   публичной части в `~/.ssh/authorized_keys` пользователя
   `DEPLOY_USER` на VPS и проверке подключения.
3. THE `deploy/README.md` SHALL перечислять имена и назначение всех
   Deploy_Secrets (`DEPLOY_SSH_KEY`, `DEPLOY_HOST`, `DEPLOY_USER`,
   `DEPLOY_PORT`, `DEPLOY_PATH`) и указывать, какие из них Secrets, а
   какие могут быть Variables.
4. THE `deploy/README.md` SHALL явно указывать, что пароль от VPS в
   автодеплое не используется и в репозитории не хранится.
