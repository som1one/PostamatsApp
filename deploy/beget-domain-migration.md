# Перенос `naprokatberu.ru` со старого сайта на наш VPS

Старый сайт сейчас живёт на shared-хостинге Бегета на домене
`naprokatberu.ru`. Цель: увести старый сайт на новый домен
`postarent.ru`, а на освободившийся `naprokatberu.ru` поставить наш
сервис (этот репозиторий, доменный compose с HTTPS через Caddy).

Документ — пошаговый чеклист в строгом порядке. Этапы 1–3 делаются на
стороне Бегета и в DNS, этап 4 — на нашем VPS, этап 5 — правки в репо
и автодеплой. Этапы нельзя переставлять: иначе либо упадёт старый
сайт, либо Caddy не сможет выпустить сертификат, либо наш бэкенд
потеряет базу.

---

## Обозначения

- `<VPS_IP>` — внешний IP нашего VPS (тот же, что в GitHub Secret
  `DEPLOY_HOST`).
- «панель Бегета» — `https://cp.beget.com/`.
- «старый сайт» — то, что сейчас отвечает на `https://naprokatberu.ru/`.
- «наш сайт» — этот репозиторий, который сейчас крутится на VPS по IP
  без HTTPS (`docker-compose.ip.yml`).

---

## Этап 1. Подготовить `postarent.ru` под старый сайт

Цель: чтобы у старого сайта появился рабочий новый адрес ДО того, как
мы заберём у него `naprokatberu.ru`.

1. В панели Бегета убедиться, что домен `postarent.ru` числится в
   аккаунте: **«Домены и поддомены»** → должен быть в списке.
   Если домена нет — зарегистрировать/перенести в аккаунт.
2. Делегировать `postarent.ru` на NS Бегета: `ns1.beget.com`,
   `ns2.beget.com`. Проверить через `nslookup -type=NS postarent.ru` —
   должны вернуться эти NS. Без этого DNS-зону в панели Бегета
   редактировать смысла нет.
3. В разделе **«Сайты»** открыть конфигурацию старого сайта и в списке
   привязанных доменов добавить `postarent.ru` и `www.postarent.ru`
   как алиасы. Не удалять `naprokatberu.ru` на этом шаге.
4. Дождаться, пока Бегет автоматически выпустит Let's Encrypt для
   `postarent.ru` (раздел **«SSL-сертификаты»**, статус `Активен`).
   Обычно 1–10 минут после того, как DNS зарезолвится.
5. Открыть `https://postarent.ru/` в браузере — должен открыться тот
   же старый сайт, что и на `https://naprokatberu.ru/`. Сертификат
   валидный.

Пока этот этап не закрыт — к этапу 2 не переходить.

---

## Этап 2. Включить редирект со старого домена на новый

Цель: пока DNS `naprokatberu.ru` ещё указывает на shared-хостинг,
посетителей старого сайта забирает `postarent.ru`. Это уменьшит
видимый простой при последующей смене DNS.

1. В панели Бегета у старого сайта выставить «основной домен» =
   `postarent.ru`.
2. Включить 301-редирект `naprokatberu.ru → postarent.ru` (опция
   «перенаправлять на основной домен» либо вручную через `.htaccess`
   старого сайта — в зависимости от того, как он устроен).
3. Проверить: `https://naprokatberu.ru/` отдаёт `301` на
   `https://postarent.ru/`. Например:

   ```bash
   curl -I https://naprokatberu.ru/
   ```

   В ответе должен быть `HTTP/2 301` и `location: https://postarent.ru/`.

Этот этап обратим: если что-то пошло не так — выключаем редирект,
старый сайт снова отвечает на `naprokatberu.ru` напрямую.

---

## Этап 3. Освободить `naprokatberu.ru` и переключить DNS на VPS

Здесь точка невозврата для старого сайта на `naprokatberu.ru`.
Делать только после того, как этап 2 уже работает.

1. В панели Бегета у старого сайта **отвязать** домен
   `naprokatberu.ru` (убрать из списка доменов сайта). Сам домен из
   аккаунта НЕ удалять — нам нужно править его DNS-зону.
2. Если на `naprokatberu.ru` была почта Бегета и её надо сохранить —
   выписать текущие записи `MX`, `TXT (SPF)`, `_dmarc`, `_domainkey.*`,
   `mail` (A/CNAME). После переноса зоны их придётся вернуть руками.
   Если почты не было — пропускаем.
3. В разделе **«DNS»** у домена `naprokatberu.ru` поменять записи:

   | Тип | Имя | Значение         | TTL |
   |-----|-----|------------------|-----|
   | A   | `@` | `<VPS_IP>`       | 300 |
   | A   | `www` | `<VPS_IP>`     | 300 |
   | A   | `api` | `<VPS_IP>`     | 300 |

   Удалить старые `A`/`CNAME` для `@`, `www`, `api`, которые ведут на
   shared-хостинг. Если были MX/SPF и они нужны (см. п.2) — сразу
   восстановить их в новой зоне.
4. Дождаться пропагации. Проверка с локальной машины:

   ```bash
   nslookup naprokatberu.ru
   nslookup api.naprokatberu.ru
   nslookup www.naprokatberu.ru
   ```

   Все три должны отдавать `<VPS_IP>`. Может занять до 10–30 минут,
   иногда дольше из-за кешей провайдеров.

Пока DNS не зарезолвился на `<VPS_IP>` — Caddy на VPS не сможет
получить сертификат Let's Encrypt. К этапу 4 переходим только после
того, как `nslookup` снаружи стабильно показывает наш IP.

---

## Этап 4. Перевести VPS с IP-конфига на доменный compose

Сейчас на VPS работает `deploy/docker-compose.ip.yml` без TLS. Надо
поднять `deploy/docker-compose.beget.yml`, который использует Caddy с
автоматическим Let's Encrypt по `APP_DOMAIN`/`API_DOMAIN`.

Все шаги — на VPS, под пользователем `DEPLOY_USER`, в каталоге
`DEPLOY_PATH`.

### 4.1. Сохранить базу старого стека

Volume Postgres у IP- и доменного compose разные (имена проектов
`postamats-ip` и `postamats-prod`), поэтому новый стек не увидит
старую базу автоматически. Снимаем дамп.

```bash
cd "$DEPLOY_PATH"
mkdir -p backups
docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml \
  exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  > "backups/postamats-$(date +%Y%m%d-%H%M%S).sql"
ls -lh backups/
```

`POSTGRES_USER`/`POSTGRES_DB` берём из `deploy/.env.ip`. Дамп должен
быть ненулевого размера. Без успешного дампа на следующий шаг не идём.

### 4.2. Подготовить `deploy/.env` под доменную конфигурацию

```bash
cp deploy/.env.example deploy/.env
nano deploy/.env
```

Проставить значения:

```dotenv
APP_DOMAIN=naprokatberu.ru
API_DOMAIN=api.naprokatberu.ru
NEXT_PUBLIC_API_BASE_URL=https://api.naprokatberu.ru
NEXT_PUBLIC_YANDEX_MAPS_API_KEY=<тот же ключ, что в .env.ip>
POSTGRES_DB=<тот же, что в .env.ip>
POSTGRES_USER=<тот же, что в .env.ip>
POSTGRES_PASSWORD=<тот же, что в .env.ip>
```

Креды Postgres обязаны совпадать с `deploy/.env.ip`, иначе после
восстановления дампа права в БД не сойдутся.

### 4.3. Остановить IP-стек

```bash
docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml down
```

`down` без `-v` — данные старых volume (`postgres_data`, `redis_data`,
`backend_uploads`) остаются на диске. Дамп у нас уже снят, но пускай
лежит как страховка.

### 4.4. Поднять доменный стек и накатить дамп

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml build
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml up -d db redis
# дать Postgres стартовать
sleep 10
# восстановить дамп в чистую базу
cat backups/postamats-*.sql | \
  docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml \
  exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
# теперь миграции и приложение
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml run --rm migrate
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml up -d
```

Для `backend_uploads` (загруженные пользователями файлы) volume в
обоих compose-файлах называется одинаково (`backend_uploads`), но
project name разный, так что docker создаст новый пустой. Если файлы
важны — перед `up -d` скопировать содержимое старого volume в новый:

```bash
docker run --rm \
  -v postamats-ip_backend_uploads:/from \
  -v postamats-prod_backend_uploads:/to \
  alpine sh -c "cp -av /from/. /to/"
```

### 4.5. Проверить, что всё поднялось и есть HTTPS

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml ps
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml logs --tail=100 caddy
curl -I https://naprokatberu.ru/
curl -I https://api.naprokatberu.ru/health
```

Признаки успеха:

- все контейнеры в `running`/`Up`;
- логи Caddy показывают успешный `certificate obtained` для
  `naprokatberu.ru`, `www.naprokatberu.ru`, `api.naprokatberu.ru`;
- `curl -I https://naprokatberu.ru/` отдаёт `200`;
- `curl -I https://api.naprokatberu.ru/health` отдаёт `200`;
- `https://www.naprokatberu.ru/` редиректит на `https://naprokatberu.ru/`.

Если Caddy не может получить сертификат — почти всегда дело в DNS
(этап 3 ещё не пропагировался) или в том, что `80/tcp` и `443/tcp`
закрыты файрволом VPS. Проверить:

```bash
ss -ltnp | grep -E ':(80|443) '
```

---

## Этап 5. Переключить автодеплой на доменный compose

Сейчас GitHub Actions гонит `deploy/deploy-ip.sh`
(`docker-compose.ip.yml`). После этапа 4 это уже неправильный путь:
автодеплой будет каждый раз пытаться поднять параллельный IP-стек.
Меняем код в репо.

Ниже — список правок (применяет агент в отдельном коммите, после
того как этап 4 закрыт и подтверждён в проде):

1. `deploy/deploy.sh` — оставить как «доменный» entrypoint, добавить
   ту же проверку готовности backend и идемпотентный запуск
   `scripts.migrate_lockers_to_real`, что сейчас в `deploy-ip.sh`.
2. `.github/workflows/deploy.yml`:
   - в проверке существующих env-файлов поменять `deploy/.env.ip` на
     `deploy/.env`;
   - заменить `bash deploy/deploy-ip.sh` на `bash deploy/deploy.sh`;
   - в блоке readiness-проверки заменить `--env-file deploy/.env.ip
     -f deploy/docker-compose.ip.yml` на `--env-file deploy/.env -f
     deploy/docker-compose.beget.yml`.
3. `deploy/README.md` — поменять «основной» сценарий с IP на доменный,
   IP оставить как fallback/дев-режим.
4. `.kiro/steering/push-every-change.md` не трогаем.

После мержа:

- В GitHub Secrets ничего менять не надо: `DEPLOY_HOST`/`DEPLOY_USER`/
  `DEPLOY_PORT`/`DEPLOY_PATH`/`DEPLOY_SSH_KEY` те же.
- На VPS уже должен лежать заполненный `deploy/.env` (этап 4.2),
  иначе workflow остановится на проверке env-файлов.
- Первый автодеплой после мержа сделает `git reset --hard origin/main`
  и поднимет доменный стек той же командой, что мы прогнали руками на
  этапе 4.

---

## Этап 6. Подчистить хвосты

После 24–48 часов стабильной работы:

1. В панели Бегета убрать редирект `naprokatberu.ru → postarent.ru`
   на стороне старого сайта (он всё равно уже не получает запросов,
   но чтобы не было путаницы в конфиге).
2. Удалить алиас `naprokatberu.ru` из настроек старого сайта, если он
   ещё там почему-то остался.
3. У `naprokatberu.ru` в DNS вернуть TTL обратно к нормальному
   значению (3600 или сколько было).
4. На VPS удалить старые volume IP-стека, если файлы из них уже
   скопированы:

   ```bash
   docker volume rm postamats-ip_postgres_data postamats-ip_redis_data \
     postamats-ip_backend_uploads
   ```

5. Дамп `backups/postamats-*.sql` — оставить минимум на месяц, потом
   можно убрать.

---

## Откат

Если на этапе 4 что-то пошло не так и наш сайт не поднялся —
максимально быстрый откат:

1. На VPS:

   ```bash
   docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml down
   docker compose --env-file deploy/.env.ip -f deploy/docker-compose.ip.yml up -d
   ```

2. В DNS `naprokatberu.ru` вернуть `A`-записи на shared-хостинг
   Бегета (значения, которые были до этапа 3 — заранее их выписать!).
3. В панели Бегета вернуть `naprokatberu.ru` в список доменов
   старого сайта.

После отката можно спокойно разбираться, в чём была причина, и
повторять этап 4 заново.
