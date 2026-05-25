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

1. WHEN коммит пушится в ветку `main` Repository, THE Deploy_Workflow SHALL запуститься автоматически на runner-е `ubuntu-latest` в течение 60 секунд с момента получения push-события.
2. WHEN Deploy_Workflow стартует по push в `main`, THE Deploy_Job SHALL подключиться к VPS по SSH, используя `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PORT` и `SSH_Key` из Deploy_Secrets, с таймаутом установления SSH-соединения 30 секунд.
3. WHEN SSH-сессия с VPS установлена, THE Deploy_Job SHALL последовательно перейти в директорию `DEPLOY_PATH`, выполнить `git fetch origin`, затем `git reset --hard origin/main`, и только после успешного завершения этих шагов запустить Deploy_Script.
4. WHEN Deploy_Script завершился с кодом 0 в пределах общего лимита выполнения Deploy_Workflow в 10 минут, THE Deploy_Workflow SHALL завершиться со статусом `success`.
5. IF любой из обязательных секретов (`DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PORT`, `SSH_Key`) отсутствует или пуст на момент старта Deploy_Job, THEN THE Deploy_Workflow SHALL завершиться со статусом `failure` без попытки SSH-подключения и с сообщением об ошибке, указывающим имя недостающего секрета.
6. IF Deploy_Script завершился с ненулевым кодом возврата или общий лимит выполнения Deploy_Workflow в 10 минут превышен, THEN THE Deploy_Workflow SHALL завершиться со статусом `failure` с сообщением об ошибке, указывающим код возврата или причину таймаута, без отката уже выполненных шагов на VPS.
7. WHILE другой Deploy_Workflow по push в `main` уже выполняется, THE Deploy_Workflow для последующих push в `main` SHALL ставиться в очередь и запускаться последовательно после завершения предыдущего, без отмены ни одного из них.

### Requirement 2: Ручной запуск деплоя через workflow_dispatch

**User Story:** Как разработчик, я хочу запускать деплой вручную из UI
GitHub Actions без пуша новых коммитов, так чтобы переразвернуть
текущий `main` (например, после правки секрета на сервере).

#### Acceptance Criteria

1. THE Deploy_Workflow SHALL объявлять триггер `workflow_dispatch` так, чтобы в UI GitHub Actions репозитория `som1one/PostamatsApp` на странице данного workflow отображалась кнопка "Run workflow", позволяющая запустить его вручную.
2. WHEN пользователь запускает Deploy_Workflow вручную через `workflow_dispatch` (независимо от того, какая ветка выбрана в выпадающем списке "Use workflow from"), THE Deploy_Workflow SHALL выполнять деплой из состояния HEAD ветки `main` (`origin/main`) и проходить тот же сценарий деплоя, что и при push в `main` (Requirement 1, criteria 2–4).
3. IF пользователь, не имеющий прав `write` на репозиторий `som1one/PostamatsApp`, пытается запустить Deploy_Workflow через `workflow_dispatch`, THEN THE Deploy_Workflow SHALL не запускаться, полагаясь на стандартный механизм авторизации GitHub Actions (запуск `workflow_dispatch` доступен только пользователям с правом `write` или выше), и состояние сервера и ветки `main` SHALL оставаться неизменным.
4. WHEN Deploy_Workflow запускается через `workflow_dispatch`, THE Deploy_Workflow SHALL использовать ту же concurrency-группу, что и запуски по push в `main`, и SHALL сериализоваться с ними так, что одновременно выполняется не более одного запуска этой группы, а последующие запуски ожидают завершения текущего согласно стандартному поведению `concurrency` в GitHub Actions.

### Requirement 3: Сериализация параллельных деплоев

**User Story:** Как разработчик, я хочу, чтобы два деплоя не выполнялись
одновременно на одном сервере, так чтобы избежать гонок при `git reset`,
билде образов и применении миграций.

#### Acceptance Criteria

1. THE Deploy_Workflow SHALL объявлять группу `concurrency` с одним фиксированным ключом (например, `deploy-vps-prod`), идентичным для всех триггеров (`push` в `main`, `workflow_dispatch`) и всех веток, без подстановки `github.ref`, `github.run_id` или иных переменных, делающих ключ различным между запусками.
2. THE Deploy_Workflow SHALL устанавливать `cancel-in-progress: false` в группе `concurrency`, чтобы новые запуски ставились в очередь и ожидали завершения текущего Deploy_Job, не прерывая выполняющиеся миграции и билд образов.
3. WHEN Deploy_Workflow уже выполняет Deploy_Job на VPS и приходит новый push в `main` или новый `workflow_dispatch`, THE Deploy_Workflow SHALL поставить новый запуск в очередь и стартовать его только после завершения (success или failure) текущего Deploy_Job, не запуская параллельный Deploy_Job на том же VPS.
4. THE Deploy_Workflow SHALL гарантировать инвариант: в любой момент времени на целевом VPS выполняется не более одного Deploy_Job — то есть число одновременно активных Deploy_Job в статусе `in_progress` для данной concurrency-группы не превышает 1.

### Requirement 4: Падение деплой-скрипта на сервере

**User Story:** Как разработчик, я хочу, чтобы при падении любого шага
деплоя (build, migrate, up) workflow помечался как failed и в логах было
видно, что именно упало, так чтобы починить проблему по логам.

#### Acceptance Criteria

1. IF любая команда внутри Deploy_Script (`docker compose build`, `docker compose run --rm migrate`, `docker compose up -d`) завершилась с кодом возврата, отличным от 0, THEN THE Deploy_Script SHALL прекратить выполнение последующих команд и THE Deploy_Job SHALL завершиться с тем же ненулевым кодом возврата.
2. IF Deploy_Job завершился с ненулевым кодом возврата, THEN THE Deploy_Workflow SHALL завершиться со статусом `failure`.
3. IF любая команда внутри Deploy_Script завершилась с кодом возврата, отличным от 0, THEN THE Deploy_Script SHALL вывести в лог Deploy_Workflow имя упавшего шага (одно из: `build`, `migrate`, `up`) и stdout, и stderr этой команды до момента падения.
4. IF Deploy_Workflow завершился со статусом `failure`, THEN THE Deploy_Workflow SHALL НЕ выполнять автоматический откат коммита в Repository.
5. IF Deploy_Workflow завершился со статусом `failure`, THEN THE Deploy_Workflow SHALL НЕ откатывать состояние Docker-контейнеров на VPS к предыдущей версии.

### Requirement 5: Видимость логов деплоя в GitHub Actions

**User Story:** Как разработчик, я хочу видеть полный stdout/stderr
деплой-скрипта прямо в логах GitHub Actions, так чтобы не ходить на
сервер за логами при каждой ошибке.

#### Acceptance Criteria

1. WHEN Deploy_Job выполняет команды по SSH на VPS, THE Deploy_Job SHALL построчно записывать stdout и stderr этих команд в лог соответствующего шага GitHub Actions с задержкой не более 5 секунд между появлением строки на VPS и её появлением в логе шага.
2. WHEN Deploy_Script печатает строку в stdout или stderr, THE Deploy_Workflow SHALL отображать эту строку в логе шага не позднее чем через 5 секунд после её появления и до завершения Deploy_Job, без потери строк и без изменения порядка строк относительно порядка их вывода Deploy_Script.
3. IF Deploy_Script завершился с кодом возврата, отличным от нуля, THEN THE Deploy_Job SHALL завершиться со статусом failed и THE Deploy_Workflow SHALL сохранить в логе шага весь полученный к этому моменту stdout и stderr Deploy_Script.
4. IF SSH-соединение между Deploy_Job и VPS было разорвано до завершения Deploy_Script, THEN THE Deploy_Job SHALL завершиться со статусом failed и THE Deploy_Workflow SHALL вывести в лог шага сообщение об ошибке с указанием хоста VPS и причины разрыва соединения.
5. WHEN Deploy_Workflow стримит stdout или stderr в лог шага, THE Deploy_Workflow SHALL заменять значения секретов, объявленных в Deploy_Job, на маску до записи строки в лог, так чтобы исходные значения секретов не появлялись в логе шага.

### Requirement 6: Обработка ошибок SSH-подключения

**User Story:** Как разработчик, я хочу получать понятную ошибку, если
SSH-ключ невалидный или сервер недоступен, так чтобы быстро понять,
что проблема в инфраструктуре, а не в коде.

#### Acceptance Criteria

1. WHEN Deploy_Job инициирует SSH-подключение к VPS, THE Deploy_Job SHALL установить TCP connect timeout 60 секунд и DNS resolution timeout 10 секунд для попытки подключения.
2. IF TCP-подключение к `DEPLOY_HOST:DEPLOY_PORT` не установлено в течение 60 секунд без явного отказа, THEN THE Deploy_Job SHALL завершиться с ненулевым кодом возврата и категорией ошибки `timeout`.
3. IF удалённый хост активно отклоняет TCP-подключение (connection refused), THEN THE Deploy_Job SHALL завершиться с ненулевым кодом возврата и категорией ошибки `connection refused`.
4. IF DNS-резолвинг имени VPS не завершён успешно в течение 10 секунд или возвращает ошибку отсутствия записи, THEN THE Deploy_Job SHALL завершиться с ненулевым кодом возврата и категорией ошибки `unknown host`.
5. IF вывод SSH-клиента содержит подстроку `Permission denied` И подстроку `publickey`, THEN THE Deploy_Job SHALL завершиться с ненулевым кодом возврата и категорией ошибки `permission denied (publickey)`.
6. IF SSH-клиент сообщает о несовпадении или отсутствии host key (host key verification failed), THEN THE Deploy_Job SHALL завершиться с ненулевым кодом возврата, категорией ошибки `host key verification failed` и сообщением, явно указывающим на проблему проверки host key.
7. IF на этапе SSH-подключения к VPS возникает ошибка любой из категорий `timeout`, `connection refused`, `unknown host`, `permission denied (publickey)` или `host key verification failed`, THEN THE Deploy_Job SHALL не выполнять на VPS ни одной удалённой команды, включая `git fetch`, `git reset` и Deploy_Script.
8. WHEN SSH-подключение к VPS завершается ошибкой любой из определённых категорий, THE Deploy_Job SHALL записать в лог шага host, port, категорию ошибки и длительность попытки подключения с точностью до 0.1 секунды.

### Requirement 7: Хранение секретов только в GitHub Secrets/Variables

**User Story:** Как разработчик, я хочу, чтобы SSH-ключ, IP сервера,
пользователь, порт и путь к проекту никогда не попадали в репозиторий,
так чтобы доступ к VPS не утёк через git-историю.

#### Acceptance Criteria

1. WHEN Deploy_Workflow стартует, THE Deploy_Workflow SHALL читать `SSH_Key` исключительно из GitHub Secret `DEPLOY_SSH_KEY` через выражение `${{ secrets.DEPLOY_SSH_KEY }}`, без какого-либо fallback на литералы, переменные окружения runner-а или файлы в репозитории.
2. IF GitHub Secret `DEPLOY_SSH_KEY` отсутствует или пустой на момент старта Deploy_Workflow, THEN THE Deploy_Workflow SHALL завершиться с ненулевым кодом возврата на шаге проверки секретов до выполнения любых шагов установки SSH-соединения и SHALL вывести сообщение об ошибке, указывающее имя отсутствующего секрета, без раскрытия его значения.
3. THE Deploy_Workflow SHALL читать `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PORT`, `DEPLOY_PATH` исключительно через выражения `${{ secrets.* }}` или `${{ vars.* }}`, и THE файл `.github/workflows/deploy.yml` SHALL НЕ содержать литеральных значений IP-адресов, имён пользователей, номеров портов и путей к проекту, относящихся к целевому VPS.
4. IF любой из `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PORT`, `DEPLOY_PATH` отсутствует или равен пустой строке после раскрытия выражения, THEN THE Deploy_Workflow SHALL завершиться с ненулевым кодом возврата на шаге проверки переменных до открытия SSH-соединения и SHALL указать в сообщении об ошибке имена отсутствующих переменных, без раскрытия их значений.
5. THE Repository SHALL НЕ содержать ни в working tree, ни в индексе git, ни в отслеживаемых файлах текущего HEAD: файлы `deploy/.env.ip`, `backend/.env.production`, файлы приватных SSH-ключей с именами `id_rsa`, `id_ed25519`, файлы с расширениями `.pem`, `.key`, и любой файл, содержащий пароль от VPS в открытом виде.
6. WHEN Deploy_Workflow выполняет любой шаг, в котором используются `DEPLOY_SSH_KEY`, `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PORT`, `DEPLOY_PATH` (далее Deploy_Secrets), THE Deploy_Workflow SHALL передавать их значения только через `${{ secrets.* }}` или `${{ vars.* }}` и SHALL регистрировать каждое значение Deploy_Secrets в механизме маскирования GitHub Actions так, чтобы значение замещалось маркером `***` в логах шагов и job summary.
7. IF шаг Deploy_Workflow выводит значение любого Deploy_Secret в stdout или stderr через команды `echo`, `cat`, `env`, `printenv` или эквивалентные команды печати окружения, THEN THE Deploy_Workflow SHALL считаться невалидным и SHALL быть отклонён на этапе review до слияния в защищённую ветку.

### Requirement 8: Сохранность данных и env-файлов на сервере

**User Story:** Как разработчик, я хочу, чтобы автодеплой не терял
загруженные файлы и не перезаписывал ручные `.env`-файлы на сервере,
так чтобы пользовательские данные и секреты переживали любой деплой.

#### Acceptance Criteria

1. WHILE Deployment выполняется, THE Deploy_Job SHALL сохранять docker named volume `backend_uploads` (определённый в `docker-compose.ip.yml`) без вызова `docker volume rm`, без `docker compose down -v` и без пересоздания, так чтобы идентификатор и содержимое volume оставались идентичными состоянию до запуска Deployment.
2. WHEN Deploy_Job выполняет `git reset --hard origin/main` в `DEPLOY_PATH`, THE Deploy_Job SHALL сохранять файлы `deploy/.env.ip` и `backend/.env.production` на VPS без изменений (контрольная сумма SHA-256 и mtime каждого файла после `git reset` SHALL совпадать со значениями до `git reset`), поскольку оба файла находятся в `.gitignore` и вне индекса git.
3. IF файл `deploy/.env.ip` или `backend/.env.production` отсутствует в `DEPLOY_PATH` на момент запуска Deploy_Job, THEN THE Deploy_Job SHALL прервать Deployment со статусом `failed` до выполнения `git reset --hard` и SHALL вернуть сообщение об ошибке, идентифицирующее отсутствующий файл, без создания, перезаписи или модификации каких-либо файлов в `DEPLOY_PATH`.
4. IF Deployment завершился со статусом `success`, THEN THE Backend_Uploads_Volume SHALL содержать тот же набор файлов (по относительным путям внутри volume) и то же содержимое каждого файла (совпадение SHA-256 для каждого файла), что и на момент непосредственно перед запуском Deploy_Job.
5. IF Deployment завершился со статусом `failed` на любом шаге после запуска контейнеров, THEN THE Deploy_Job SHALL оставить `backend_uploads`, `deploy/.env.ip` и `backend/.env.production` в том же состоянии, что и до запуска Deployment (без частичных перезаписей и без удаления).

### Requirement 9: Состояние контейнеров после успешного деплоя

**User Story:** Как разработчик, я хочу, чтобы после зелёного workflow
контейнеры `web` и `backend` были запущены, а миграции применены, так
чтобы зелёный билд означал работающий prod.

#### Acceptance Criteria

1. WHEN Deploy_Script выполняется, THE Deploy_Job SHALL запустить alembic-миграции через сервис `migrate` из `deploy/docker-compose.ip.yml` с таймаутом 300 секунд и SHALL стартовать сервисы `web` и `backend` только после того, как сервис `migrate` завершился с кодом возврата 0.
2. WHEN Deployment завершился со статусом `success`, THE сервисы `web` и `backend` из `deploy/docker-compose.ip.yml` SHALL находиться в Docker-состоянии `running`, наблюдаемом через `docker compose ps` на VPS, в течение 60 секунд после команды `up -d`.
3. IF сервис `migrate` завершился с ненулевым кодом возврата, THEN THE Deploy_Job SHALL НЕ выполнять `up -d` для сервисов `web` и `backend`, SHALL завершиться с ненулевым кодом возврата и SHALL НЕ помечать Deployment как успешный.
4. IF сервисы `web` или `backend` не достигли Docker-состояния `running` в течение 60 секунд после `up -d` ИЛИ завершились с ненулевым кодом возврата, THEN THE Deploy_Job SHALL завершиться с ненулевым кодом возврата и SHALL НЕ помечать Deployment как успешный.

### Requirement 10: Документация по первичной настройке

**User Story:** Как новый член команды, я хочу прочитать в
`deploy/README.md`, как сгенерировать SSH-ключ, положить публичную часть
на сервер и настроить GitHub Secrets, так чтобы поднять автодеплой с
нуля без догадок.

#### Acceptance Criteria

1. THE `deploy/README.md` SHALL содержать раздел верхнего уровня с заголовком "Автодеплой из GitHub" (Markdown-уровень `##`), в котором явно перечислены оба триггера workflow — `push` в ветку `main` и ручной запуск `workflow_dispatch` — и приведена относительная ссылка на файл `.github/workflows/deploy.yml`.
2. THE `deploy/README.md` SHALL содержать пошаговую инструкцию по настройке SSH-доступа, включающую: (a) команду генерации ключа `ssh-keygen -t ed25519 -C "<comment>" -f <path>` без passphrase, (b) явное указание, что приватная часть ключа сохраняется только в GitHub Secret `DEPLOY_SSH_KEY` и не коммитится в репозиторий, (c) явное указание, что публичная часть ключа (`*.pub`) добавляется в файл `~/.ssh/authorized_keys` пользователя `DEPLOY_USER` на VPS.
3. WHEN читатель следует инструкции из criterion 2, THE `deploy/README.md` SHALL предоставлять команду проверки подключения вида `ssh -i <path> -p <DEPLOY_PORT> <DEPLOY_USER>@<DEPLOY_HOST>` и явно указывать критерий успеха: подключение устанавливается без запроса пароля и без интерактивного ввода.
4. THE `deploy/README.md` SHALL содержать таблицу или список всех пяти параметров деплоя — `DEPLOY_SSH_KEY`, `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PORT`, `DEPLOY_PATH` — где для каждого указано: назначение одной фразой, тип хранения (Secret или Variable), и пример формата значения (например, для `DEPLOY_HOST` — IP-адрес или DNS-имя, для `DEPLOY_PORT` — целое число от 1 до 65535, для `DEPLOY_PATH` — абсолютный путь на VPS, для `DEPLOY_SSH_KEY` — содержимое приватного ключа в формате OpenSSH, для `DEPLOY_USER` — имя системного пользователя).
5. THE `deploy/README.md` SHALL указывать путь добавления параметров в интерфейсе GitHub: Settings → Secrets and variables → Actions, с явным разделением на вкладки "Secrets" и "Variables" в соответствии с типом хранения из criterion 4.
6. THE `deploy/README.md` SHALL содержать явное утверждение, что аутентификация на VPS в автодеплое выполняется только по SSH-ключу, и что пароль пользователя `DEPLOY_USER` не хранится ни в репозитории, ни в GitHub Secrets, ни в GitHub Variables, ни передаётся через workflow.
