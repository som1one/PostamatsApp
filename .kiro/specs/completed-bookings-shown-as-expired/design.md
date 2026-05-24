# Completed Bookings Shown As Expired — Bugfix Design

## Overview

В клиентском веб-интерфейсе (`web/`) логика расчёта «дедлайн-метки» бронирования
ошибочно помечает завершённые (терминальные) бронирования как «Просрочено», как
только проходит плановое время окончания (`plannedEndAt`).

Дефект — чисто клиентский. Бэкенд (`backend/utils/rental_overdue.py`,
`mark_overdue_rentals`) корректно держит `RentalStatus.COMPLETED` как терминал и
никогда не переводит его в `OVERDUE`. UI интерпретирует данные неверно, потому
что в обоих местах (список бронирований и страница деталей заказа) условие
«просрочено» проверяется как `status === "overdue" || diffMs <= 0` — без учёта
того, что аренда уже завершена.

Стратегия фикса: ввести единый чистый helper
`isTerminalRentalStatus(status)` в `web/src/shared/rentalStatus.ts`, который
возвращает `true` для `completed`, и добавить ранний выход из функции расчёта
дедлайн-метки в обоих местах ДО проверки `diffMs <= 0`. Это устраняет
дублирование и предотвращает дрейф двух копий логики.

## Glossary

- **Bug_Condition (C)**: `rental.status === "completed" AND rental.plannedEndAt
  IS NOT NULL AND now > new Date(rental.plannedEndAt).getTime()`.
- **Property (P)**: для входов, удовлетворяющих C, dл deadline-meta НЕ должна
  быть «danger»/«Просрочено» (требования 2.1, 2.2). Для всех остальных входов
  (¬C) результат функции должен совпадать с поведением до фикса (req 3.x).
- **Preservation**: поведение для всех входов, не удовлетворяющих C, остаётся
  бит-в-бит идентичным исходной функции (включая мышь, иные клавиши, активные/
  просроченные/предстоящие/отменённые сценарии).
- **`getRentalDeadlineMeta(rental, nowMs)`**: чистая функция в
  `web/src/app/rentals/RentalsClient.tsx` (~строка 111), возвращающая
  `DeadlineMeta | null` для карточек на странице `/rentals`.
- **OrderDetail deadline IIFE**: анонимная inline-функция в
  `web/src/app/profile/orders/[id]/OrderDetailClient.tsx` (~строки 581–619),
  дублирующая ту же логику для страницы `/profile/orders/[id]`.
- **`RentalStatus`**: статус аренды (бэкендовский enum, на фронте — обычная
  строка). Релевантные значения: `active`, `overdue`, `pickup_ready`,
  `pickup_opened`, `return_in_progress`, `completed`, `cancelled`.
- **Terminal status**: статус, после установки которого бронирование уже не
  может стать «активным» снова. В рамках этого фикса трактуем как `completed`.
  `cancelled` сюда не включаем — см. раздел «Out-of-scope» и обсуждение в Fix
  Implementation.

## Bug Details

### Bug Condition

Дефект срабатывает, когда у бронирования терминальный статус `completed`,
поле `plannedEndAt` заполнено, и текущее «клиентское» время позднее
`plannedEndAt`. В этом случае ветка `rental.status === "overdue" || diffMs <= 0`
ложно срабатывает по второму операнду и возвращает «danger»-мету с заголовком
«Просрочено на …» и предложением «оформить возврат».

**Formal Specification:**

```
FUNCTION isBugCondition(rental, nowMs)
  INPUT: rental of type RentalListItem (status: string, plannedEndAt: string|null, ...),
         nowMs of type number
  OUTPUT: boolean

  IF rental.status ≠ "completed"        THEN RETURN false
  IF rental.plannedEndAt IS NULL        THEN RETURN false
  plannedEndMs := parseDate(rental.plannedEndAt)
  IF plannedEndMs IS NaN                THEN RETURN false
  RETURN nowMs > plannedEndMs
END FUNCTION
```

### Examples

- `status = "completed"`, `plannedEndAt = 2025-01-01T12:00`, `now = 2025-01-01T12:01`
  - Ожидаемое: `getRentalDeadlineMeta` → `null` (мета не показывается, статус
    «Завершено» формируется отдельно в `StatusPill`).
  - Фактическое (до фикса): возвращается `{ tone: "danger", title: "Просрочено
    на 1 минуту", text: "Стоит оформить возврат как можно скорее." }`.
- `status = "completed"`, `plannedEndAt = 2025-01-01T12:00`, `now = 2025-01-02T12:00`
  - Ожидаемое: `null`.
  - Фактическое: «Просрочено на 1 день».
- `status = "completed"`, `plannedEndAt = 2025-01-01T12:00`, `now = 2025-01-01T11:00`
  - C(X) НЕ выполняется (now < plannedEndAt). Поведение такое же, как до фикса:
    функция падает в финальный `return null` (терминал не входит в
    `["pickup_ready","pickup_opened","active"]`).
- `status = "active"`, `plannedEndAt = 2025-01-01T12:00`, `now = 2025-01-01T12:01`
  - C(X) НЕ выполняется. Должно по-прежнему возвращаться «danger / Просрочено».

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**

- `status = "active"` или `status = "overdue"` с прошедшим `plannedEndAt` → все
  так же отображается «Просрочено на {длительность}» (req 3.1, 3.2).
- `status ∈ {"active","pickup_ready","pickup_opened"}` с будущим `plannedEndAt`
  → «До возврата: {длительность}» (req 3.3); специальная ветка «Получение
  через {wait}» для `pickup_ready/pickup_opened` за >1 ч до старта остаётся.
- `status = "return_in_progress"` → «Возврат уже начат» (req 3.4).
- `status = "cancelled"` → визуальное представление не меняется (req 3.5). На
  helper-уровне это означает, что `isTerminalRentalStatus("cancelled") = false`.
- `status = "completed"` с `now < plannedEndAt` → возвращается `null`, никакой
  меты не рисуется (req 3.6).

**Scope:**
Любые входы, у которых `status ≠ "completed"` ИЛИ `plannedEndAt` пустое/невалидное
ИЛИ `now ≤ plannedEndAt`, должны быть полностью неизменны после фикса.

## Hypothesized Root Cause

1. **Отсутствие проверки терминального статуса перед `diffMs <= 0`.**
   В обоих местах последовательность веток такая:
   1) `return_in_progress` → success-мета;
   2) проверка наличия и валидности `plannedEndAt`;
   3) `if (rental.status === "overdue" || diffMs <= 0)` → danger.
   Терминальные `completed`/`cancelled` нигде не отсекаются и проваливаются
   во вторую часть OR, помечая запись как просроченную.

2. **Дублирование одинаковой логики в двух файлах.** Из-за копии правки в одном
   месте автоматически рассинхронизируют второе. Это объясняет, почему дефект
   одинаково проявляется и в списке `/rentals`, и на детальной странице
   `/profile/orders/[id]`.

3. (Отвергнуто) проблема на бэкенде. Проверено: `mark_overdue_rentals`
   переводит в `OVERDUE` только записи `ACTIVE`; завершённое бронирование
   приходит с фронта как `status = "completed"`, и сервер не возвращает его
   в активное состояние.

4. (Отвергнуто) проблема в `StatusPill`/лейблах статуса. Сам статусный лейбл
   рендерится корректно как «Завершено»; неверная информация даёт именно
   deadline-meta-блок над/под StatusPill.

## Correctness Properties

Property 1: Bug Condition — Завершённое бронирование не помечается как «Просрочено»

_For any_ `(rental, nowMs)`, удовлетворяющего `isBugCondition` (т.е.
`rental.status === "completed"`, `plannedEndAt` валиден и `nowMs > plannedEndMs`),
исправленная функция `getRentalDeadlineMeta'(rental, nowMs)` SHALL вернуть
значение, у которого `tone ≠ "danger"` и `title` НЕ содержит подстроку
«Просрочено». На практике для текущего набора веток это означает возврат `null`.

**Validates: Requirements 2.1, 2.2**

Property 2: Preservation — поведение для всех остальных входов не меняется

_For any_ `(rental, nowMs)`, НЕ удовлетворяющего `isBugCondition`, исправленная
функция `getRentalDeadlineMeta'(rental, nowMs)` SHALL вернуть значение,
структурно равное тому, что возвращала исходная функция
`getRentalDeadlineMeta(rental, nowMs)` до фикса (тот же `tone`, тот же `title`,
тот же `text`, тот же `Icon`, либо обе — `null`).

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

## Fix Implementation

### Changes Required

Принимая, что гипотеза о корневой причине верна:

**Новый файл:** `web/src/shared/rentalStatus.ts`

Содержит чистый, без зависимостей, helper:

```ts
// Терминальные статусы, для которых не нужно показывать deadline-overlay,
// даже если plannedEndAt уже в прошлом.
//
// ВНИМАНИЕ: cancelled сюда НЕ включаем — req 3.5 требует сохранить текущее
// представление отменённого бронирования. Если потребуется расширить набор
// (например, при появлении нового терминала), это делается в одном месте.
export function isTerminalRentalStatus(status: string | null | undefined): boolean {
  return status === "completed";
}
```

**Файл 1:** `web/src/app/rentals/RentalsClient.tsx`

- Добавить импорт `isTerminalRentalStatus` из `@/shared/rentalStatus`.
- В функцию `getRentalDeadlineMeta` добавить ранний выход — ПЕРЕД блоком
  `if (rental.status === "overdue" || diffMs <= 0)` (или, эквивалентно, в
  самом начале функции, если решено упростить):

```ts
function getRentalDeadlineMeta(rental: RentalListItem, nowMs: number): DeadlineMeta | null {
  if (rental.status === "return_in_progress") { /* ... unchanged ... */ }

  // Терминальные статусы (например, "completed") не рисуют deadline-плашку
  // вне зависимости от того, прошло ли плановое окончание.
  if (isTerminalRentalStatus(rental.status)) {
    return null;
  }

  if (!rental.plannedEndAt) return null;
  // ... остальное без изменений ...
}
```

**Файл 2:** `web/src/app/profile/orders/[id]/OrderDetailClient.tsx`

- Импортировать `isTerminalRentalStatus`.
- В inline-IIFE (строки ~581–619), сразу после ветки `return_in_progress`
  и до проверки `plannedEndAt`, добавить:

```ts
if (isTerminalRentalStatus(rental.status)) {
  return null;
}
```

### Tradeoffs: inline-fix vs shared helper

| Вариант                          | Плюсы                                             | Минусы                                                           |
|----------------------------------|---------------------------------------------------|------------------------------------------------------------------|
| Inline `if (status === "completed") return null` в каждом из двух файлов | минимум файлов, минимальная диффа                 | дублирование, легко расходится при будущих правках; нет единой точки расширения |
| **Shared `isTerminalRentalStatus` (выбрано)** | одна точка истины, легко тестируется юнит-тестом, расширяется добавлением статуса в один if | +1 файл (~5 строк) и пара импортов                              |

Выбираем shared helper: поверхность риска регрессии при добавлении нового
терминала в будущем (например, если появится `archived`) сводится к правке
одной строки, а не двух разнесённых мест в JSX-файлах.

### Locations to Change (summary)

- `web/src/shared/rentalStatus.ts` — НОВЫЙ файл, экспорт `isTerminalRentalStatus`.
- `web/src/app/rentals/RentalsClient.tsx` — импорт + ранний `return null` в
  `getRentalDeadlineMeta`.
- `web/src/app/profile/orders/[id]/OrderDetailClient.tsx` — импорт + ранний
  `return null` в inline-IIFE deadline-блока.

### Behaviour Matrix

`now` относительно `plannedEndAt`: `<` означает `now < plannedEndAt` (будущее),
`>` означает `now > plannedEndAt` (прошлое); `n/a` — поле не заполнено или
не используется этой веткой.

| status               | plannedEndAt vs now | До фикса (F)                          | После фикса (F')                       | Соответствие        |
|----------------------|---------------------|----------------------------------------|----------------------------------------|---------------------|
| `completed`          | `>` (прошло)        | **`danger`: «Просрочено»** (BUG)       | `null` (мета не отображается)          | req 2.1, 2.2 (FIX)  |
| `completed`          | `<` (будущее)       | `null`                                 | `null`                                 | req 3.6 (PRESERVE)  |
| `completed`          | `plannedEndAt = null`| `null`                                | `null`                                 | PRESERVE            |
| `active`             | `>` (прошло)        | `danger`: «Просрочено»                 | `danger`: «Просрочено»                 | req 3.1 (PRESERVE)  |
| `active`             | `<` (будущее)       | `warn`: «До возврата»                  | `warn`: «До возврата»                  | req 3.3 (PRESERVE)  |
| `overdue`            | любое               | `danger`: «Просрочено»                 | `danger`: «Просрочено»                 | req 3.2 (PRESERVE)  |
| `pickup_ready`       | старт >1ч в будущем | `warn`: «Получение через …»            | `warn`: «Получение через …»            | PRESERVE            |
| `pickup_ready`       | `<` (близкое будущее)| `warn`: «До возврата»                 | `warn`: «До возврата»                  | req 3.3 (PRESERVE)  |
| `pickup_opened`      | `<` / `>`           | как `pickup_ready`                     | без изменений                          | PRESERVE            |
| `return_in_progress` | любое               | `success`: «Возврат уже начат»         | `success`: «Возврат уже начат»         | req 3.4 (PRESERVE)  |
| `cancelled`          | `<` / `>`           | существующее представление             | существующее представление (без изменений) | req 3.5 (PRESERVE)  |

Замечание: для `cancelled` существующее представление формируется в окружающем
JSX (карточка отмены/refund), а не в `getRentalDeadlineMeta`/IIFE; helper его не
трогает. Это явный design-выбор — не расширять набор «терминальных» статусов в
рамках этого фикса.

## Testing Strategy

### Validation Approach

По решению пользователя — **только детерминированные unit-тесты на `vitest`**,
без property-based testing. Property 1 и Property 2 из
секции «Correctness Properties» остаются концептуальной основой; в тестах
они материализуются как явное перечисление детерминированных кейсов,
покрывающих каждую строку «Behaviour Matrix» выше.

Двухфазный подход:

1. **Exploratory bug condition checking** — на UNFIXED коде запустить
   юнит-тест, повторяющий бизнес-сценарий пользователя, чтобы получить
   конкретный counterexample. Тест должен упасть до фикса и пройти после.
2. **Fix + preservation checking** — после фикса прогнать матрицу детерминированных
   `vitest` юнит-тестов, по одному кейсу на каждую строку Behaviour Matrix, для
   `isTerminalRentalStatus`, `getRentalDeadlineMeta` (RentalsClient) и
   `computeOrderDeadlineMeta` (вынесенная из IIFE функция в OrderDetailClient).

Помимо тестов, обязательны `npm run lint`, `npm run typecheck`, `npx vitest run`
и `npm run build`.

### Exploratory Bug Condition Checking

**Goal:** до фикса воспроизвести ошибочное поведение и подтвердить гипотезу о
корневой причине.

**Test Plan:** написать юнит-тест на `vitest`, дёргающий `getRentalDeadlineMeta`
с `status="completed"`, `plannedEndAt = "2025-01-01T12:00:00Z"`, `nowMs =
Date.parse("2025-01-01T12:01:00Z")`, и проверить, что текущая (нефиксированная)
реализация возвращает `tone === "danger"` и `title.includes("Просрочено")`.
Запустить ДО внедрения helper'а — этот тест должен упасть на assert
«не danger», что подтвердит гипотезу. После фикса этот же тест должен пройти
(в нём assert переворачивается на «не danger / null»).

Аналогичный тест запускается против `computeOrderDeadlineMeta` — функции,
которую необходимо вынести из inline-IIFE в `OrderDetailClient.tsx` (см.
раздел Tasks). Извлечение делается ОТДЕЛЬНЫМ pure-refactor шагом без изменения
поведения, чтобы дефект сохранился и был воспроизведён точно тем же тестом.

**Test Cases:**

1. **Completed-just-after-end** — `status="completed"`, `plannedEndAt=12:00`,
   `now=12:01` (на нефикс-коде получит `tone="danger"`).
2. **Completed-long-after-end** — то же, но `now = plannedEndAt + 1 day`.
3. **Completed-before-end (control)** — `status="completed"`, `now < plannedEndAt`
   → уже на нефикс-коде должно быть `null`; служит контролем, что мы не
   ломаем эту ветку.

**Expected Counterexamples:**

- `getRentalDeadlineMeta({status:"completed", plannedEndAt:"2025-01-01T12:00:00Z", ...}, Date.parse("2025-01-01T12:01:00Z")) === { tone: "danger", title: "Просрочено на 1 минута", ... }`
- Возможные причины: ветка `diffMs <= 0` срабатывает раньше любой проверки на
  терминальный статус.

### Fix Checking

**Goal:** для всех входов, удовлетворяющих `isBugCondition`, исправленная
функция возвращает значение без `tone === "danger"` и без подстроки
«Просрочено» в `title` (на практике — `null`).

**Pseudocode:**

```
FOR ALL (rental, nowMs) WHERE isBugCondition(rental, nowMs) DO
  meta := getRentalDeadlineMeta_fixed(rental, nowMs)
  ASSERT meta === null OR (meta.tone ≠ "danger" AND NOT meta.title.includes("Просрочено"))
END FOR
```

В тестах это материализуется как явное перечисление детерминированных
кейсов из строк Behaviour Matrix, у которых `status = "completed"` и
`plannedEndAt < now` (см. раздел «Unit Tests From Properties» ниже).

### Preservation Checking

**Goal:** для всех входов, НЕ удовлетворяющих `isBugCondition`, исправленная
функция возвращает то же самое, что и оригинальная.

**Pseudocode:**

```
FOR ALL (rental, nowMs) WHERE NOT isBugCondition(rental, nowMs) DO
  ASSERT deepEqual(
    getRentalDeadlineMeta_original(rental, nowMs),
    getRentalDeadlineMeta_fixed(rental, nowMs)
  )
END FOR
```

**Подход:** детерминированные `vitest` юнит-тесты, перечисляющие все строки
Behaviour Matrix (включая обе подветки `pickup_ready`: `>1ч до старта` и
`<1ч / прошлое`). Для каждой строки тест строит фиктивный `RentalListItem`,
вызывает `getRentalDeadlineMeta` (соответственно `computeOrderDeadlineMeta`)
и проверяет конкретный ожидаемый результат через `expect(...).toEqual(...)`
или, для текстовых полей с локализованной длительностью, через
`expect(meta.title).toBe(...)` / `expect(meta.tone).toBe(...)`.

**Test Plan:** разместить тесты в:

- `web/src/shared/__tests__/rentalStatus.test.ts` — юнит-тесты для
  `isTerminalRentalStatus`.
- `web/src/app/rentals/__tests__/getRentalDeadlineMeta.test.ts` —
  Behaviour-Matrix-кейсы для `getRentalDeadlineMeta` плюс ровно тот сценарий
  пользователя из секции Exploratory Bug Condition Checking.
- `web/src/app/profile/orders/[id]/__tests__/computeOrderDeadlineMeta.test.ts` —
  Behaviour-Matrix-кейсы для функции, вынесенной из IIFE в `OrderDetailClient.tsx`.

Чтобы тесты могли вызывать функции напрямую, IIFE на странице деталей заказа
выносится в именованную чистую функцию `computeOrderDeadlineMeta(rental, nowMs)`
в том же файле и экспортируется. Это делается ОТДЕЛЬНЫМ pure-refactor шагом
ДО внедрения фикса, чтобы тест «exploratory» сначала упал, а потом прошёл.

### Unit Tests

Все тесты — детерминированные `vitest` юнит-тесты, без property-based
генерации. Структура — `describe.each` / `it.each` по таблице
Behaviour Matrix.

#### `isTerminalRentalStatus`

| Вход                  | Ожидаемое значение |
|-----------------------|--------------------|
| `"completed"`         | `true`             |
| `"cancelled"`         | `false`            |
| `"active"`            | `false`            |
| `"overdue"`           | `false`            |
| `"pickup_ready"`      | `false`            |
| `"pickup_opened"`     | `false`            |
| `"return_in_progress"`| `false`            |
| `null`                | `false`            |
| `undefined`           | `false`            |

#### `getRentalDeadlineMeta` (RentalsClient)

По одному тесту на каждую строку Behaviour Matrix:

1. `completed` + `now > plannedEndAt` (FIX) → `null`.
2. `completed` + `now < plannedEndAt` (PRESERVE req 3.6) → `null`.
3. `completed` + `plannedEndAt = null` (PRESERVE) → `null`.
4. `active` + `now > plannedEndAt` (PRESERVE req 3.1) → `tone: "danger"`,
   `title.startsWith("Просрочено")`.
5. `active` + `now < plannedEndAt` (PRESERVE req 3.3) → `tone: "warn"`,
   `title.startsWith("До возврата")`.
6. `overdue` + `now > plannedEndAt` (PRESERVE req 3.2) → `tone: "danger"`.
7. `pickup_ready` + старт >1ч в будущем (PRESERVE) → `tone: "warn"`,
   `title.startsWith("Получение через")`.
8. `pickup_ready` + старт скоро (PRESERVE req 3.3) → `tone: "warn"`,
   `title.startsWith("До возврата")`.
9. `pickup_opened` + `now < plannedEndAt` (PRESERVE) → как `pickup_ready`.
10. `return_in_progress` (PRESERVE req 3.4) → `tone: "success"`,
    `title === "Возврат уже начат"`.
11. `cancelled` + любое (PRESERVE req 3.5) → `null` (на helper-уровне; видимое
    представление формирует окружающий JSX).
12. **User-reproduction (FIX)**: `status="completed"`,
    `plannedEndAt="2025-01-01T12:00:00Z"`,
    `nowMs=Date.parse("2025-01-01T12:01:00Z")` → `null`.

Тесты до фикса прогоняются на нефиксированном коде: кейсы 1, 12 ОЖИДАЕМО
проваливаются (это и есть exploration-counterexample); кейсы 2–11 ОЖИДАЕМО
проходят (preservation-baseline).

#### `computeOrderDeadlineMeta` (OrderDetailClient)

Зеркальный набор кейсов 1–12, тот же `expect(...)` для каждой строки.

### Unit Tests From Properties

Эта секция — материализация Property 1 / Property 2 как явного перечисления
детерминированных кейсов:

- **Property 1 (Bug Condition / Fix Checking)** материализуется кейсами 1 и 12
  выше (для каждой из двух функций) — оба входа удовлетворяют
  `isBugCondition`, и assert требует `meta === null` (т.е. ни `danger`, ни
  «Просрочено» в `title`).
- **Property 2 (Preservation)** материализуется кейсами 2–11 (для каждой из
  двух функций) — каждый кейс соответствует строке Behaviour Matrix, в которой
  `isBugCondition` ложно, и assert требует точное соответствие тому же
  значению, что возвращает оригинальная функция (`tone`, `title`-префикс,
  `null` — в зависимости от строки).
- **Helper-symmetry** для `isTerminalRentalStatus` материализована таблицей в
  начале раздела «Unit Tests» — это дискретное перечисление всех релевантных
  входов.

### Integration Tests

Полноценная интеграция через Playwright в этом репозитории не настроена для
`web/`, поэтому интеграционная проверка остаётся ручной:

- На странице `/rentals`: бронирование со `status="completed"` после прохода
  `plannedEndAt` отображается как «Завершено» без плашки «Просрочено» и без
  кнопки «Оформить возврат».
- На странице `/profile/orders/[id]` для того же бронирования отсутствует
  блок `rental-deadline rental-deadline-danger`.
- Для бронирования со `status="active"` и `plannedEndAt` в прошлом плашка
  «Просрочено» по-прежнему отображается (контроль регрессии req 3.1).

## Verification & Build Steps

После реализации фикса (на этапе tasks):

1. `cd web && npm install` (после добавления devDep `vitest` в `package.json`).
2. `npm run lint` — должен пройти с `--max-warnings=0` (как настроено в скрипте).
3. `npm run typecheck` — `tsc --noEmit` без ошибок.
4. `npx vitest run` (или `npm test` после добавления `"test": "vitest run"` в
   `scripts`) — все юнит-тесты зелёные, включая exploration-тест из Task 1.
5. `npm run build` — `next build` без ошибок.
6. Ручная проверка двух сценариев из секции Integration Tests на dev-сервере
   (`npm run dev`, порт 3001), либо на staging-сборке.

Деплой на сервер из этой задачи исключён.

## Out-of-scope

Явно НЕ входит в scope этого фикса:

- Любые изменения в `backend/` (rental_overdue, mark_overdue_rentals,
  RentalStatus enum).
- Любые изменения в админ-панели (`admin/`).
- Деплой на сервер (выполняется пользователем отдельно).
- Изменение лейблов `StatusPill` или маппинга статусов в `web/src/shared/format.ts`.
- Рефакторинг окружающего UI (карточка бронирования, блок `detail-actions`,
  меню действий).
- Расширение набора терминальных статусов на `cancelled` или новые статусы —
  заблокировано req 3.5; при необходимости — отдельный спек.
- Унификация других дублирующихся функций между `RentalsClient.tsx` и
  `OrderDetailClient.tsx` (например, `formatDurationLabel`) — отдельный
  чисто-рефакторинговый спек.
