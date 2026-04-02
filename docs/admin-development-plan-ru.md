# План разработки админки по ТЗ

Документ собирает в одном месте план реализации MVP-админки для сервиса аренды товаров через постаматы.

Основание:

- `docs/mvp-ru.md`
- `docs/monolith-options-and-app-spec-ru.md`
- `docs/api-mvp-contract.md`
- `docs/p0-api-spec-ru.md`
- текущая структура `backend/` и `mobile/`

## 1. Цель админки

Админка в MVP должна быть не "кабинетом управления всем", а операционным backoffice для ежедневной работы команды.

Ключевые задачи:

- вход администратора;
- очередь ручной верификации пользователей;
- просмотр пользователей и их статусов;
- мониторинг постаматов и доступности товаров;
- просмотр аренд и ручное завершение проблемных сценариев;
- просмотр товаров и физических единиц;
- минимальный аудит операторских действий.

## 2. Что входит в MVP

### P0

- `login`
- `users`
- `user details`
- `verification queue`
- `lockers`
- `locker details`
- `products`
- `inventory`
- `rentals`
- `rental details`

### P1 сразу после P0

- `incidents`
- блокировка пользователя
- аварийное открытие ячейки
- создание и редактирование постаматов
- создание и редактирование SKU
- ручное обновление физической единицы товара

### Не брать в первый релиз

- BI-аналитику и дашборды
- Excel/PDF-выгрузки
- сложную матрицу ролей
- франчайзи-контур
- глубокую автоматизацию инцидентов

## 3. Что уже есть в проекте

### Уже есть

- FastAPI backend с доменными моделями `User`, `VerificationRequest`, `AdminUser`, `LockerLocation`, `InventoryUnit`, `Rental`, `RentalEvent`
- клиентские API для авторизации, верификации, товаров, постаматов, бронирования и платежей
- enum'ы и модели, которые можно переиспользовать в админке
- мобильное приложение на Expo/React

### Пока нет

- admin API-роутов из `docs/api-mvp-contract.md`
- admin auth flow
- middleware/guard для прав администратора
- отдельного web-приложения под админку
- аудита действий админа на уровне API

## 4. Рекомендуемая реализация

### Backend

- оставить текущий FastAPI backend
- добавить отдельный namespace `/api/v1/admin/*`
- не смешивать клиентскую и админскую авторизацию
- использовать `AdminUser` как отдельную сущность доступа

### Frontend

- создать новый workspace `admin/`
- стек:
  - `React`
  - `Vite`
  - `TypeScript`
  - `React Router`
  - `TanStack Query`
  - `React Hook Form`
  - простая UI-система без тяжёлого дизайн-фреймворка

### Почему так

- ТЗ прямо выделяет web-админку как отдельный контур;
- текущий репозиторий уже разделён на `backend/` и `mobile/`;
- админка не должна зависеть от Expo/web-режима мобильного приложения;
- отдельный `admin/` ускорит маршрутизацию, авторизацию и дальнейшее развитие backoffice.

## 5. План разработки по этапам

## Этап 0. Уточнение и фиксация контракта

Цель: убрать неоднозначности до старта реализации.

Задачи:

- зафиксировать базовый URL админки и backend prefix, лучше сразу `/api/v1/admin`
- подтвердить роли MVP: `super_admin`, `operator`
- подтвердить состав P0 и P1 экранов
- согласовать, какие действия доступны `operator`, а какие только `super_admin`
- определить формат аудита: кто, когда, что изменил
- определить способ создания первого администратора: seed, SQL, CLI-команда

Результат:

- короткий ADR или обновлённый документ с финальным scope
- список admin endpoints для первой итерации

## Этап 1. Backend foundation для админки

Цель: подготовить безопасную и расширяемую базу.

Задачи:

- добавить admin auth:
  - `POST /admin/auth/login`
  - `POST /admin/auth/refresh`
- выпустить отдельные access/refresh токены для админской сессии
- добавить dependency для проверки admin token
- добавить проверку `is_active` и `role`
- подготовить seed первого `AdminUser`
- настроить CORS для отдельного web-origin админки
- унифицировать error response под admin API

Результат:

- рабочий вход в админку
- защищённый backend-контур для следующих модулей

Зависимости:

- решение по хранению и созданию администратора

## Этап 2. Users и Verification queue

Цель: закрыть самую критичную операционную задачу MVP.

Задачи backend:

- `GET /admin/users`
- `GET /admin/users/:userId`
- `POST /admin/users/:userId/approve-verification`
- `POST /admin/users/:userId/reject-verification`
- `POST /admin/users/:userId/block` как P1
- добавить фильтры:
  - phone
  - verification status
  - blocked state
- вернуть в user details:
  - профиль
  - текущий verification request
  - последние аренды
  - последние платежи
  - ссылки на документы

Задачи frontend:

- экран логина
- layout админки
- список пользователей
- очередь верификации
- карточка пользователя
- подтверждение/отклонение верификации с reason

Результат:

- оператор может руками обработать KYC от начала до конца

## Этап 3. Rentals и операторские действия

Цель: дать команде контроль над проблемными арендными сценариями.

Задачи backend:

- `GET /admin/rentals`
- `GET /admin/rentals/:rentalId`
- `POST /admin/rentals/:rentalId/cancel`
- `POST /admin/rentals/:rentalId/force-complete`
- фильтры:
  - city
  - locker
  - status
  - overdue
- вернуть в деталях аренды:
  - user
  - inventory unit
  - locker
  - payment state
  - rental events timeline

Задачи frontend:

- список аренд
- фильтры и быстрые статусы
- карточка аренды
- таймлайн событий
- confirm-модалки для ручных действий

Результат:

- оператор видит зависшие аренды и может завершить их без прямой работы с БД

## Этап 4. Lockers и мониторинг точек

Цель: закрыть контроль инфраструктуры постаматов.

Задачи backend:

- `GET /admin/lockers`
- `GET /admin/lockers/:lockerId`
- `POST /admin/lockers/:lockerId/open-cell` как минимум в P1
- позже:
  - `POST /admin/lockers`
  - `PATCH /admin/lockers/:lockerId`
- вернуть:
  - статус точки
  - список ячеек
  - последние события
  - агрегаты по доступным товарам

Задачи frontend:

- список постаматов
- карточка постамата
- статус онлайн/оффлайн/maintenance
- таблица ячеек и доступности
- аварийное действие `open cell` под ролью

Результат:

- команда видит состояние точки и может вмешаться при сбое выдачи или возврата

## Этап 5. Products и Inventory

Цель: дать операционный контроль над каталогом и физическими единицами.

Задачи backend:

- `GET /admin/products`
- `POST /admin/products` как P1
- `PATCH /admin/products/:productId` как P1
- `GET /admin/inventory-units`
- `PATCH /admin/inventory-units/:unitId` как P1
- фильтры inventory:
  - locker
  - product
  - status
  - serial number

Задачи frontend:

- список товаров
- список физических единиц
- отображение статусов `available`, `reserved`, `rented`, `damaged`, `maintenance`, `lost`
- P1-формы редактирования SKU и inventory unit

Результат:

- оператор и администратор видят, где лежит конкретный экземпляр товара и в каком он состоянии

## Этап 6. Audit, UX hardening и доступы

Цель: довести админку до безопасного пилотного использования.

Задачи:

- записывать ключевые admin actions:
  - approve/reject verification
  - cancel/force-complete rental
  - block user
  - open cell
  - inventory update
- скрывать опасные действия по роли
- добавить пустые состояния, ошибки, retry и skeleton'ы
- добавить debounce для поиска и серверную пагинацию
- предусмотреть auto-refresh для очереди верификации и активных аренд
- логировать request id и actor id

Результат:

- админка пригодна для ежедневной работы без ручного дебага по логам

## Этап 7. QA и выпуск

Цель: стабилизировать MVP перед pilot.

Задачи:

- smoke-тест всех P0 экранов
- проверка role-based access
- проверка happy path и failure path по:
  - verification
  - rentals
  - lockers
- ручная проверка сценариев:
  - approve verification
  - reject verification
  - find stuck rental
  - force complete rental
  - inspect locker state
- подготовить `.env` и инструкции запуска для `admin/`

Результат:

- админка готова к внутреннему использованию командой operations

## 6. Рекомендуемая последовательность реализации

Лучший порядок для MVP:

1. backend admin auth
2. users + verification queue
3. rentals + manual operations
4. lockers monitoring
5. products + inventory
6. audit + role restrictions
7. QA + release prep

Причина:

- верификация и проблемные аренды дают максимальную ценность в pilot;
- каталог и инвентарь важны, но не блокируют старт так же сильно;
- инциденты можно сначала закрывать через rental details и locker details, а отдельный экран вынести в P1.

## 7. Экранный план frontend

### Общий shell

- login page
- app layout with sidebar
- top bar with current admin and logout
- protected routes

### Страницы P0

- `/login`
- `/users`
- `/users/:id`
- `/verification`
- `/rentals`
- `/rentals/:id`
- `/lockers`
- `/lockers/:id`
- `/products`
- `/inventory`

### Общие UI-паттерны

- таблицы с серверной пагинацией
- статусные бейджи
- search + filters
- drawers или detail pages для просмотра деталей
- confirm dialog для опасных действий
- toast/snackbar для результата операций

## 8. API backlog для первой итерации

### Обязательно

- `POST /admin/auth/login`
- `POST /admin/auth/refresh`
- `GET /admin/users`
- `GET /admin/users/:userId`
- `POST /admin/users/:userId/approve-verification`
- `POST /admin/users/:userId/reject-verification`
- `GET /admin/rentals`
- `GET /admin/rentals/:rentalId`
- `GET /admin/lockers`
- `GET /admin/lockers/:lockerId`
- `GET /admin/products`
- `GET /admin/inventory-units`

### Следом

- `POST /admin/users/:userId/block`
- `POST /admin/rentals/:rentalId/cancel`
- `POST /admin/rentals/:rentalId/force-complete`
- `POST /admin/lockers/:lockerId/open-cell`
- `POST /admin/products`
- `PATCH /admin/products/:productId`
- `PATCH /admin/inventory-units/:unitId`

## 9. Критерии готовности MVP

Админку можно считать готовой к pilot, если:

- администратор может войти и сохранить сессию;
- оператор видит очередь верификации и может approve/reject;
- можно быстро найти пользователя по телефону;
- можно открыть детали аренды и понять, что произошло;
- можно увидеть зависшие или просроченные аренды;
- можно посмотреть статус постамата и его ячеек;
- можно увидеть список товаров и физических единиц;
- все опасные действия логируются;
- нет необходимости править данные напрямую в БД для типовых операционных задач.

## 10. Основные риски

- нет отдельной admin auth модели сессии, поэтому важно не переиспользовать клиентские токены без явного разграничения
- некоторые P1-операции потребуют аккуратного изменения доменной логики, а не только новых CRUD-ручек
- без audit trail ручные действия оператора будут плохо расследоваться
- без seed/CLI для первого администратора запуск админки упрётся в bootstrap
- если сразу делать все P1-экраны, есть риск размыть срок MVP

## 11. Практический таймлайн

Если делать прагматично, то разумный план такой:

1. День 1: scope freeze, admin auth, seed admin
2. День 2-3: users, verification queue, user details API
3. День 4-5: rentals list, rental details, manual operations
4. День 6: lockers list, locker details
5. День 7: products list, inventory list
6. День 8: frontend polishing, guards, errors, empty states
7. День 9: audit trail и role restrictions
8. День 10: smoke QA и выпуск внутренней версии

Если сроки жёстче, то можно урезать P0 до:

- login
- verification queue
- users
- rentals
- lockers

А `products` и `inventory` выпустить второй волной.
