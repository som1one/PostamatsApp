# Requirements Document

## Introduction

Сейчас на хостинге Beget под доменом `naprokatberu.ru` работает чужой сайт (далее — Старый_Сайт), а наш проект развёрнут на VPS в IP-режиме (compose-файл `deploy/docker-compose.ip.yml` с проектным именем `postamats-ip`, прокси `deploy/Caddyfile.ip`, скрипт `deploy/deploy-ip.sh`, GitHub Actions `.github/workflows/deploy.yml`).

Цель миграции:

1. Переключить Старый_Сайт в панели Beget с домена `naprokatberu.ru` на новый домен `postarent.ru` (домен `postarent.ru` остаётся за Старым_Сайтом на Beget; файлы и БД Старого_Сайта не трогаем).
2. Освободившийся домен `naprokatberu.ru` направить на наш VPS и переключить наш стек из IP-режима в доменный режим (compose `deploy/docker-compose.beget.yml`, Caddy с автоматическим HTTPS Let's Encrypt, `APP_DOMAIN=naprokatberu.ru`, `API_DOMAIN=api.naprokatberu.ru`).
3. Сохранить данные нашего проекта (Postgres и загруженные файлы) при смене проектного имени Docker Compose с `postamats-ip` на `postamats-prod` (разные volume namespaces: `postamats-ip_postgres_data`/`postamats-ip_backend_uploads` против `postamats-prod_postgres_data`/`postamats-prod_backend_uploads`).
4. Обновить автодеплой так, чтобы push в `main` разворачивал стек в доменном режиме, а не в IP-режиме.
5. Редирект `naprokatberu.ru` → `postarent.ru` не настраивать.

Допустимо короткое окно недоступности нашего проекта на время переключения compose-стеков и переноса данных.

## Glossary

- **Beget_Panel**: панель управления хостингом Beget, в которой настраиваются домены Старого_Сайта.
- **Старый_Сайт**: чужой сайт, размещённый на Beget; до миграции открывается на `naprokatberu.ru`, после миграции должен открываться на `postarent.ru`.
- **DNS_Provider**: регистратор/DNS-провайдер, у которого ведутся NS-записи домена `naprokatberu.ru`.
- **VPS_Stack**: docker compose стек нашего проекта на VPS, состоящий из сервисов `caddy`, `web`, `backend`, `migrate`, `db`, `redis`.
- **IP_Mode**: текущий режим VPS_Stack: compose-файл `deploy/docker-compose.ip.yml`, env-файл `deploy/.env.ip`, Caddyfile `deploy/Caddyfile.ip`, проектное имя docker `postamats-ip`, доступ по HTTP по IP сервера.
- **Domain_Mode**: целевой режим VPS_Stack: compose-файл `deploy/docker-compose.beget.yml`, env-файл `deploy/.env`, Caddyfile `deploy/Caddyfile`, проектное имя docker `postamats-prod`, HTTPS на доменах `naprokatberu.ru` и `api.naprokatberu.ru`.
- **Caddy**: reverse proxy и ACME-клиент Let's Encrypt в составе VPS_Stack.
- **Postgres_Volume**: docker volume для данных PostgreSQL (`postgres_data`), смонтированный в сервис `db` под `/var/lib/postgresql/data`.
- **Uploads_Volume**: docker volume для пользовательских загрузок (`backend_uploads`), смонтированный в сервис `backend` под `/app/assets/runtime-uploads`.
- **Deployment_Pipeline**: связка `.github/workflows/deploy.yml` и скриптов `deploy/deploy-ip.sh`/`deploy/deploy.sh`, выполняющая автодеплой на VPS по push в `main` и по `workflow_dispatch`.
- **Operator**: инженер, выполняющий миграцию вручную (Beget_Panel, DNS_Provider, SSH на VPS).

## Requirements

### Requirement 1: Перенастройка доменов Старого_Сайта в Beget_Panel

**User Story:** Как Operator, я хочу в Beget_Panel переключить Старый_Сайт с `naprokatberu.ru` на `postarent.ru`, чтобы освободить домен `naprokatberu.ru` и при этом сохранить работу Старого_Сайта на новом домене.

#### Acceptance Criteria

1. WHEN Operator выполняет привязку домена в Beget_Panel, THE Beget_Panel SHALL связать домен `postarent.ru` с тем же сайтом Beget, который до миграции обслуживал `naprokatberu.ru`.
2. WHEN Operator выполняет отвязку домена в Beget_Panel, THE Beget_Panel SHALL удалить привязку домена `naprokatberu.ru` к Старому_Сайту.
3. THE Operator SHALL не изменять файлы и базу данных Старого_Сайта в Beget_Panel в рамках этой миграции.
4. WHEN привязка `postarent.ru` завершена и DNS-записи `postarent.ru` указывают на серверы Beget, THE Старый_Сайт SHALL открываться по адресу `https://postarent.ru/` с тем же содержимым, что отдавалось ранее по `naprokatberu.ru`.
5. THE Operator SHALL не настраивать в Beget_Panel редирект с `naprokatberu.ru` на `postarent.ru`.

### Requirement 2: DNS для домена `naprokatberu.ru`

**User Story:** Как Operator, я хочу перенаправить DNS-записи домена `naprokatberu.ru` на IP нашего VPS, чтобы посетители `naprokatberu.ru` попадали в наш VPS_Stack, а не на Beget.

#### Acceptance Criteria

1. WHEN Operator обновляет DNS-зону `naprokatberu.ru` у DNS_Provider, THE DNS_Provider SHALL содержать A-запись `naprokatberu.ru` со значением, равным публичному IP-адресу VPS.
2. WHEN Operator обновляет DNS-зону `naprokatberu.ru` у DNS_Provider, THE DNS_Provider SHALL содержать A-запись `api.naprokatberu.ru` со значением, равным публичному IP-адресу VPS.
3. WHILE миграция выполняется, THE Operator SHALL удалить или перенаправить старые DNS-записи `naprokatberu.ru` и `api.naprokatberu.ru`, ранее указывавшие на серверы Beget.
4. WHERE DNS_Provider поддерживает запись `www.naprokatberu.ru`, THE DNS_Provider SHALL содержать A-запись или CNAME `www.naprokatberu.ru`, разрешающуюся на тот же IP VPS, что и `naprokatberu.ru`.
5. IF после обновления DNS публичный резолвер возвращает для `naprokatberu.ru` IP-адрес, не совпадающий с IP VPS, THEN THE Operator SHALL не переходить к переключению VPS_Stack в Domain_Mode до момента распространения DNS.

### Requirement 3: Переключение VPS_Stack из IP_Mode в Domain_Mode с сохранением данных

**User Story:** Как Operator, я хочу переключить VPS_Stack из IP_Mode в Domain_Mode без потери данных пользователей, чтобы наш проект продолжил работать на `naprokatberu.ru` с теми же учётками, бронированиями и загруженными файлами.

#### Acceptance Criteria

1. WHEN Operator переводит VPS_Stack в Domain_Mode, THE VPS_Stack SHALL использовать compose-файл `deploy/docker-compose.beget.yml` и env-файл `deploy/.env` вместо `deploy/docker-compose.ip.yml` и `deploy/.env.ip`.
2. THE VPS_Stack в Domain_Mode SHALL получать значения `APP_DOMAIN=naprokatberu.ru` и `API_DOMAIN=api.naprokatberu.ru` через `deploy/.env`.
3. THE VPS_Stack в Domain_Mode SHALL получать значение `NEXT_PUBLIC_API_BASE_URL=https://api.naprokatberu.ru` через `deploy/.env` на этапе сборки сервиса `web`.
4. WHEN Operator выполняет переключение compose-стека, THE VPS_Stack SHALL сохранить данные PostgreSQL Старого_Состояния (БД нашего проекта в IP_Mode) и сделать их доступными сервису `db` в Domain_Mode под тем же именем БД, пользователем и паролем, что заданы в `deploy/.env`.
5. WHEN Operator выполняет переключение compose-стека, THE VPS_Stack SHALL сохранить файлы из Uploads_Volume IP_Mode и сделать их доступными сервису `backend` в Domain_Mode по пути `/app/assets/runtime-uploads`.
6. IF проектное имя Docker Compose отличается между IP_Mode (`postamats-ip`) и Domain_Mode (`postamats-prod`), THEN THE Operator SHALL выполнить перенос содержимого Postgres_Volume и Uploads_Volume из namespace `postamats-ip_*` в namespace `postamats-prod_*` до первого запуска сервиса `backend` в Domain_Mode.
7. WHEN VPS_Stack запущен в Domain_Mode, THE сервис `migrate` SHALL выполнить `alembic upgrade head` против перенесённой базы данных и завершиться с кодом 0 до старта сервиса `backend`.
8. THE Operator SHALL остановить стек IP_Mode (`docker compose -p postamats-ip down` без удаления volumes) до запуска стека Domain_Mode, чтобы порты 80/443 на VPS не были заняты двумя стеками одновременно.
9. THE Operator SHALL не удалять docker volumes `postamats-ip_postgres_data` и `postamats-ip_backend_uploads` до подтверждения, что Domain_Mode успешно работает на сохранённых данных.

### Requirement 4: HTTPS через Let's Encrypt в Caddy

**User Story:** Как пользователь сайта `naprokatberu.ru`, я хочу заходить по HTTPS с действующим сертификатом, чтобы браузер не показывал предупреждений безопасности.

#### Acceptance Criteria

1. WHEN VPS_Stack запущен в Domain_Mode и DNS уже указывает `naprokatberu.ru` и `api.naprokatberu.ru` на IP VPS, THE Caddy SHALL автоматически выпустить и установить сертификаты Let's Encrypt для доменов `naprokatberu.ru` и `api.naprokatberu.ru`.
2. THE VPS_Stack в Domain_Mode SHALL публиковать на хосте порты `80` и `443` через сервис `caddy`.
3. WHEN клиент открывает `https://naprokatberu.ru/`, THE Caddy SHALL проксировать запрос на сервис `web` на порт `3001`.
4. WHEN клиент открывает `https://api.naprokatberu.ru/`, THE Caddy SHALL проксировать запрос на сервис `backend` на порт `8000`.
5. WHEN клиент открывает `https://www.naprokatberu.ru/<path>`, THE Caddy SHALL вернуть HTTP 301 на `https://naprokatberu.ru/<path>`.
6. THE VPS_Stack в Domain_Mode SHALL хранить выпущенные Caddy сертификаты и ACME-аккаунт в docker volume `caddy_data`, чтобы повторный запуск контейнера не приводил к перевыпуску сертификатов.
7. IF Caddy не может выпустить сертификат для `naprokatberu.ru` или `api.naprokatberu.ru` в течение 5 минут после старта стека, THEN THE Operator SHALL проверить корректность DNS-записей (Requirement 2) и доступность портов 80/443 на VPS до повторной попытки.

### Requirement 5: Обновление автодеплоя под Domain_Mode

**User Story:** Как разработчик, я хочу, чтобы автодеплой по push в `main` разворачивал стек в Domain_Mode, чтобы после миграции наш CI/CD не возвращал стек обратно в IP_Mode.

#### Acceptance Criteria

1. WHEN GitHub Actions запускает workflow `.github/workflows/deploy.yml` после миграции, THE Deployment_Pipeline SHALL выполнять на VPS скрипт, который запускает compose-файл `deploy/docker-compose.beget.yml` с env-файлом `deploy/.env`.
2. THE Deployment_Pipeline SHALL проверять наличие на VPS файлов `deploy/.env` и `backend/.env.production` до выполнения `git reset --hard origin/main`.
3. WHEN Deployment_Pipeline проверяет состояние сервисов после деплоя, THE Deployment_Pipeline SHALL ждать состояния `running` для сервисов `web`, `backend` и `caddy` стека `postamats-prod` и завершаться с ошибкой, если хотя бы один из них не достиг состояния `running` за 60 секунд.
4. THE Deployment_Pipeline SHALL не запускать `deploy/docker-compose.ip.yml` и не использовать env-файл `deploy/.env.ip` в Domain_Mode.
5. WHERE миграция постаматов в боевую конфигурацию (`scripts.migrate_lockers_to_real`) была частью IP_Mode деплоя, THE Deployment_Pipeline в Domain_Mode SHALL сохранить идемпотентный вызов этой миграции против сервиса `backend` стека `postamats-prod`.
6. IF env-файл `deploy/.env` или `backend/.env.production` отсутствует на VPS на момент деплоя, THEN THE Deployment_Pipeline SHALL завершиться с ошибкой и не выполнять `git reset --hard` и пересборку контейнеров.

### Requirement 6: Проверки после миграции

**User Story:** Как Operator, я хочу иметь чёткий чек-лист проверок после миграции, чтобы убедиться, что Старый_Сайт жив на новом домене, а наш проект работает на `naprokatberu.ru` с HTTPS и рабочей авторизацией.

#### Acceptance Criteria

1. WHEN Operator открывает в браузере `https://postarent.ru/`, THE Старый_Сайт SHALL вернуть HTTP 200 и содержимое, идентичное тому, что отдавалось по `https://naprokatberu.ru/` до миграции.
2. WHEN Operator открывает в браузере `https://naprokatberu.ru/`, THE VPS_Stack SHALL вернуть HTTP 200 и стартовую страницу нашего сервиса `web` с действующим сертификатом Let's Encrypt.
3. WHEN Operator выполняет HTTP-запрос `GET https://api.naprokatberu.ru/api/health` (или эквивалентный health-эндпоинт нашего backend), THE VPS_Stack SHALL вернуть HTTP-ответ со статусом 2xx и действующим сертификатом Let's Encrypt для `api.naprokatberu.ru`.
4. WHEN Operator выполняет вход существующего пользователя через форму авторизации на `https://naprokatberu.ru/`, THE VPS_Stack SHALL принять учётные данные, созданные ещё в IP_Mode, и установить сессию пользователя.
5. WHEN Operator выполняет регистрацию нового пользователя через форму на `https://naprokatberu.ru/`, THE VPS_Stack SHALL создать учётную запись и вернуть пользователю успешный ответ формы.
6. WHEN Operator проверяет загруженные файлы (фото объявлений, документы) после миграции, THE VPS_Stack SHALL отдавать те же файлы, что были загружены в IP_Mode, по их прежним публичным URL в пределах домена `naprokatberu.ru`.
7. IF любая из проверок 1–6 не проходит, THEN THE Operator SHALL зафиксировать конкретную проверку и причину отказа до объявления миграции завершённой.
