# P0 API: подробная спецификация ручек

Этот документ описывает P0 API для MVP аренды через постаматы.
По каждой ручке указано:

- что принимает;
- какие модели использует;
- что делает;
- какие ошибки возвращает;
- что отдаёт.

Базовые допущения:

- base path: `/api/v1`
- авторизация: `Authorization: Bearer <token>`
- деньги: в копейках, integer
- время: `ISO 8601 UTC`
- идентификаторы: `UUID`

Общий формат успешного ответа:

```json
{
  "data": {}
}
```

Общий формат ошибки:

```json
{
  "error": {
    "code": "SOME_ERROR_CODE",
    "message": "Human readable message",
    "details": {}
  }
}
```

---

## 1. Загрузка файлов

## `POST /uploads/presign`

### Кто вызывает

- mobile
- admin

### Что принимает

```json
{
  "fileName": "passport-front.jpg",
  "mimeType": "image/jpeg",
  "fileSize": 245123,
  "kind": "verification_front"
}
```

### Поля

- `fileName`: оригинальное имя файла
- `mimeType`: MIME-тип
- `fileSize`: размер файла в байтах
- `kind`: тип файла

Допустимые `kind` для MVP:

- `verification_front`
- `verification_back`
- `verification_selfie`
- `incident_attachment`
- `condition_photo_before`
- `condition_photo_after`

### Какие модели использует

- `User` или `AdminUser`
- `MediaFile`

### Что делает

1. Проверяет авторизацию.
2. Валидирует размер и MIME-тип.
3. Генерирует `fileKey`.
4. Создаёт запись `MediaFile` со статусом подготовленного файла.
5. Возвращает presigned URL или набор полей для direct upload в storage.

### Коды ошибок

- `401 UNAUTHORIZED` — нет токена или токен невалиден
- `400 INVALID_FILE_KIND` — неизвестный `kind`
- `400 INVALID_MIME_TYPE` — MIME не разрешён
- `400 FILE_TOO_LARGE` — превышен лимит размера
- `500 STORAGE_PRESIGN_FAILED` — не удалось создать ссылку

### Что отдаёт

```json
{
  "data": {
    "fileId": "uuid",
    "fileKey": "verification/2026/03/24/uuid-passport-front.jpg",
    "uploadUrl": "https://storage.example.com/...",
    "method": "PUT",
    "headers": {
      "Content-Type": "image/jpeg"
    },
    "expiresIn": 900
  }
}
```

---

## 2. Постаматы

## `GET /lockers`

### Кто вызывает

- mobile
- admin

### Что принимает

Query params:

- `cityId`
- `status`
- `hasAvailableItems`
- `page`
- `limit`

Пример:

`GET /api/v1/lockers?cityId=uuid&status=online&hasAvailableItems=true`

### Какие модели использует

- `City`
- `LockerLocation`
- `LockerCell`
- `InventoryUnit`

### Что делает

1. Валидирует `cityId`, если он передан.
2. Фильтрует постаматы по городу и статусу.
3. Считает количество доступных товаров на точке.
4. Возвращает данные для карты и списка.

### Коды ошибок

- `400 INVALID_CITY_ID`
- `404 CITY_NOT_FOUND`
- `500 LOCKERS_FETCH_FAILED`

### Что отдаёт

```json
{
  "data": {
    "lockers": [
      {
        "id": "uuid",
        "cityId": "uuid",
        "name": "Постамат на Литейном",
        "address": "Санкт-Петербург, Литейный пр., 12",
        "lat": 59.9386,
        "lon": 30.3141,
        "status": "online",
        "workingHours": {
          "mode": "daily",
          "from": "08:00",
          "to": "22:00"
        },
        "availableProductCount": 14,
        "availableUnitCount": 18
      }
    ]
  },
  "meta": {
    "page": 1,
    "limit": 20,
    "total": 1
  }
}
```

## `GET /lockers/:lockerId`

### Что принимает

- path: `lockerId`

### Какие модели использует

- `LockerLocation`
- `LockerCell`
- `InventoryUnit`
- `Product`
- `PricePlan`

### Что делает

1. Находит постамат.
2. Возвращает публичную информацию по точке.
3. Возвращает краткую доступность по товарам или агрегированный summary.

### Коды ошибок

- `404 LOCKER_NOT_FOUND`
- `500 LOCKER_FETCH_FAILED`

### Что отдаёт

```json
{
  "data": {
    "locker": {
      "id": "uuid",
      "cityId": "uuid",
      "name": "Постамат на Литейном",
      "address": "Санкт-Петербург, Литейный пр., 12",
      "lat": 59.9386,
      "lon": 30.3141,
      "status": "online",
      "workingHours": {
        "mode": "daily",
        "from": "08:00",
        "to": "22:00"
      },
      "availableProductCount": 14,
      "products": [
        {
          "productId": "uuid",
          "name": "Перфоратор Bosch",
          "available": true,
          "priceFrom": 150000
        }
      ]
    }
  }
}
```

## `GET /lockers/:lockerId/availability`

### Что принимает

- path: `lockerId`

Опционально query:

- `productId`

### Какие модели использует

- `LockerLocation`
- `LockerCell`
- `InventoryUnit`
- `Product`
- `PricePlan`

### Что делает

1. Проверяет, что постамат существует и доступен.
2. Ищет все `InventoryUnit` со статусом `available`.
3. Группирует по товарам.
4. Для каждого товара добавляет минимальный тариф.

### Коды ошибок

- `404 LOCKER_NOT_FOUND`
- `409 LOCKER_OFFLINE`
- `500 LOCKER_AVAILABILITY_FAILED`

### Что отдаёт

```json
{
  "data": {
    "lockerId": "uuid",
    "status": "online",
    "items": [
      {
        "productId": "uuid",
        "productName": "Перфоратор Bosch",
        "availableUnits": 2,
        "minDurationType": "day",
        "minDurationValue": 1,
        "priceFrom": 150000,
        "currency": "RUB"
      }
    ]
  }
}
```

---

## 3. Каталог

## `GET /products`

### Кто вызывает

- mobile
- admin

### Что принимает

Query params:

- `cityId`
- `lockerId`
- `categoryId`
- `search`
- `availableOnly`
- `page`
- `limit`

### Какие модели использует

- `ProductCategory`
- `Product`
- `ProductImage`
- `PricePlan`
- `InventoryUnit`
- `LockerLocation`

### Что делает

1. Фильтрует товары.
2. Подтягивает минимальную цену из `PricePlan`.
3. Считает availability по выбранному городу или постамату.
4. Возвращает карточки каталога.

### Коды ошибок

- `400 INVALID_FILTERS`
- `404 CATEGORY_NOT_FOUND`
- `404 LOCKER_NOT_FOUND`
- `500 PRODUCTS_FETCH_FAILED`

### Что отдаёт

```json
{
  "data": {
    "products": [
      {
        "id": "uuid",
        "categoryId": "uuid",
        "name": "Перфоратор Bosch",
        "slug": "bosch-hammer-drill",
        "coverUrl": "https://cdn.example.com/file.jpg",
        "shortDescription": "Для сверления и демонтажа",
        "brand": "Bosch",
        "priceFrom": 150000,
        "currency": "RUB",
        "available": true,
        "availableLockerCount": 3
      }
    ]
  },
  "meta": {
    "page": 1,
    "limit": 20,
    "total": 23
  }
}
```

## `GET /products/:productId`

### Что принимает

- path: `productId`
- query optional: `cityId`

### Какие модели использует

- `Product`
- `ProductImage`
- `ProductCategory`
- `PricePlan`
- `InventoryUnit`
- `LockerLocation`

### Что делает

1. Загружает карточку товара.
2. Отдаёт описание, характеристики, комплект, правила аренды.
3. Возвращает доступные тарифы.
4. Возвращает список точек, где товар доступен.

### Коды ошибок

- `404 PRODUCT_NOT_FOUND`
- `410 PRODUCT_INACTIVE`
- `500 PRODUCT_FETCH_FAILED`

### Что отдаёт

```json
{
  "data": {
    "product": {
      "id": "uuid",
      "categoryId": "uuid",
      "name": "Перфоратор Bosch",
      "slug": "bosch-hammer-drill",
      "shortDescription": "Для сверления и демонтажа",
      "fullDescription": "Подробное описание",
      "brand": "Bosch",
      "specs": {
        "power": "800W",
        "weight": "3.2kg"
      },
      "rulesText": "Использовать по назначению",
      "kitDescription": "Кейс, бур, зарядка",
      "images": [
        {
          "id": "uuid",
          "url": "https://cdn.example.com/1.jpg",
          "sortOrder": 1
        }
      ],
      "pricePlans": [
        {
          "id": "uuid",
          "name": "1 день",
          "durationType": "day",
          "durationValue": 1,
          "baseAmount": 150000,
          "currency": "RUB"
        }
      ],
      "availableLockers": [
        {
          "lockerId": "uuid",
          "name": "Постамат на Литейном",
          "address": "Санкт-Петербург, Литейный пр., 12",
          "status": "online",
          "availableUnits": 2
        }
      ]
    }
  }
}
```

## `GET /products/:productId/pricing`

### Что принимает

- path: `productId`
- query:
  - `lockerId`
  - `durationType`
  - `durationValue`

### Какие модели использует

- `Product`
- `PricePlan`
- `LockerLocation`
- `InventoryUnit`

### Что делает

1. Проверяет товар.
2. Проверяет тариф.
3. Проверяет доступность хотя бы одной единицы товара в выбранном постамате.
4. Возвращает расчёт для checkout.

### Коды ошибок

- `404 PRODUCT_NOT_FOUND`
- `404 LOCKER_NOT_FOUND`
- `404 PRICE_PLAN_NOT_FOUND`
- `409 PRODUCT_NOT_AVAILABLE`
- `409 LOCKER_OFFLINE`
- `500 PRICING_FAILED`

### Что отдаёт

```json
{
  "data": {
    "productId": "uuid",
    "lockerId": "uuid",
    "durationType": "day",
    "durationValue": 1,
    "currency": "RUB",
    "baseAmount": 150000,
    "discountAmount": 0,
    "depositAmount": 0,
    "preauthAmount": 150000,
    "totalAmount": 150000,
    "available": true
  }
}
```

---

## 4. Бронирование

## `POST /reservations/quote`

### Кто вызывает

- mobile

### Что принимает

```json
{
  "productId": "uuid",
  "lockerId": "uuid",
  "durationType": "day",
  "durationValue": 1
}
```

### Какие модели использует

- `User`
- `Product`
- `LockerLocation`
- `InventoryUnit`
- `PricePlan`
- опционально `ReservationQuote`

### Что делает

1. Проверяет access token.
2. Проверяет, что пользователь верифицирован.
3. Проверяет, что постамат online.
4. Проверяет, что товар доступен.
5. Находит подходящий `PricePlan`.
6. Возвращает финальный расчёт перед созданием брони.

### Коды ошибок

- `401 UNAUTHORIZED`
- `403 USER_NOT_VERIFIED`
- `403 USER_BLOCKED`
- `404 PRODUCT_NOT_FOUND`
- `404 LOCKER_NOT_FOUND`
- `404 PRICE_PLAN_NOT_FOUND`
- `409 LOCKER_OFFLINE`
- `409 PRODUCT_NOT_AVAILABLE`
- `500 RESERVATION_QUOTE_FAILED`

### Что отдаёт

```json
{
  "data": {
    "quote": {
      "productId": "uuid",
      "lockerId": "uuid",
      "durationType": "day",
      "durationValue": 1,
      "currency": "RUB",
      "quotedAmount": 150000,
      "preauthAmount": 150000,
      "expiresIn": 300
    }
  }
}
```

## `POST /reservations`

### Что принимает

```json
{
  "productId": "uuid",
  "lockerId": "uuid",
  "durationType": "day",
  "durationValue": 1,
  "pickupWindowMinutes": 120
}
```

### Какие модели использует

- `User`
- `Product`
- `LockerLocation`
- `InventoryUnit`
- `PricePlan`
- `Reservation`

### Что делает

1. Повторно валидирует quote.
2. Выбирает конкретный `InventoryUnit`.
3. Переводит `InventoryUnit.status` в `reserved`.
4. Создаёт `Reservation`.
5. Ставит `expires_at`.

### Коды ошибок

- `401 UNAUTHORIZED`
- `403 USER_NOT_VERIFIED`
- `403 USER_BLOCKED`
- `404 PRODUCT_NOT_FOUND`
- `404 LOCKER_NOT_FOUND`
- `404 PRICE_PLAN_NOT_FOUND`
- `409 PRODUCT_NOT_AVAILABLE`
- `409 LOCKER_OFFLINE`
- `409 ACTIVE_RESERVATION_EXISTS`
- `500 RESERVATION_CREATE_FAILED`

### Что отдаёт

```json
{
  "data": {
    "reservation": {
      "id": "uuid",
      "status": "awaiting_payment",
      "productId": "uuid",
      "inventoryUnitId": "uuid",
      "lockerId": "uuid",
      "durationType": "day",
      "durationValue": 1,
      "quotedAmount": 150000,
      "preauthAmount": 150000,
      "expiresAt": "2026-03-24T12:00:00Z"
    }
  }
}
```

## `GET /reservations/:reservationId`

### Что принимает

- path: `reservationId`

### Какие модели использует

- `Reservation`
- `Product`
- `LockerLocation`
- `PricePlan`
- `Payment`

### Что делает

1. Проверяет, что бронь принадлежит пользователю.
2. Возвращает summary брони и countdown.

### Коды ошибок

- `401 UNAUTHORIZED`
- `404 RESERVATION_NOT_FOUND`
- `403 RESERVATION_FORBIDDEN`
- `500 RESERVATION_FETCH_FAILED`

### Что отдаёт

```json
{
  "data": {
    "reservation": {
      "id": "uuid",
      "status": "awaiting_payment",
      "expiresAt": "2026-03-24T12:00:00Z",
      "product": {
        "id": "uuid",
        "name": "Перфоратор Bosch",
        "coverUrl": "https://cdn.example.com/file.jpg"
      },
      "locker": {
        "id": "uuid",
        "name": "Постамат на Литейном",
        "address": "Санкт-Петербург, Литейный пр., 12"
      },
      "pricing": {
        "quotedAmount": 150000,
        "preauthAmount": 150000,
        "currency": "RUB"
      }
    }
  }
}
```

## `POST /reservations/:reservationId/confirm`

### Что принимает

```json
{
  "paymentId": "uuid"
}
```

### Какие модели использует

- `Reservation`
- `Payment`
- `InventoryUnit`
- `LockerLocation`
- `LockerCell`
- `Rental`
- `RentalEvent`

### Что делает

1. Проверяет, что бронь принадлежит пользователю.
2. Проверяет, что у брони ещё не истёк срок.
3. Проверяет успешную предавторизацию.
4. Резервирует ячейку через интеграцию ESI.
5. Генерирует `pickup_pin`.
6. Создаёт `Rental` в статусе `pickup_ready`.
7. Переводит `Reservation.status` в `confirmed`.

### Коды ошибок

- `401 UNAUTHORIZED`
- `404 RESERVATION_NOT_FOUND`
- `404 PAYMENT_NOT_FOUND`
- `403 RESERVATION_FORBIDDEN`
- `409 RESERVATION_EXPIRED`
- `409 PAYMENT_NOT_AUTHORIZED`
- `409 LOCKER_OFFLINE`
- `502 ESI_RESERVE_FAILED`
- `500 RESERVATION_CONFIRM_FAILED`

### Что отдаёт

```json
{
  "data": {
    "rental": {
      "id": "uuid",
      "status": "pickup_ready",
      "pickupPin": "4821",
      "pickupLockerId": "uuid",
      "plannedEndAt": "2026-03-25T12:00:00Z"
    }
  }
}
```

---

## 5. Платежи

## `POST /payments/preauth`

### Кто вызывает

- mobile

### Что принимает

```json
{
  "reservationId": "uuid",
  "paymentMethodId": "uuid",
  "paymentToken": "tok_xxx"
}
```

Для MVP можно разрешить один из двух вариантов:

- `paymentMethodId`, если карта уже сохранена
- `paymentToken`, если платёж инициируется новой картой

### Какие модели использует

- `Reservation`
- `User`
- `Payment`
- `PaymentMethod` если есть

### Что делает

1. Проверяет бронь.
2. Проверяет, что бронь ещё активна.
3. Создаёт запись `Payment` типа `preauth`.
4. Инициирует операцию в ЮKassa.
5. Сохраняет `provider_payment_id`.
6. Возвращает данные для завершения оплаты на клиенте.

### Коды ошибок

- `401 UNAUTHORIZED`
- `404 RESERVATION_NOT_FOUND`
- `403 RESERVATION_FORBIDDEN`
- `409 RESERVATION_EXPIRED`
- `409 PAYMENT_ALREADY_EXISTS`
- `400 INVALID_PAYMENT_METHOD`
- `502 YOOKASSA_REQUEST_FAILED`
- `500 PAYMENT_PREAUTH_FAILED`

### Что отдаёт

```json
{
  "data": {
    "payment": {
      "id": "uuid",
      "type": "preauth",
      "status": "pending",
      "amount": 150000,
      "currency": "RUB"
    },
    "confirmation": {
      "type": "redirect",
      "confirmationUrl": "https://yookassa.ru/checkout/..."
    }
  }
}
```

## `POST /payments/webhooks/yookassa`

### Кто вызывает

- YooKassa

### Что принимает

Webhook payload провайдера.

Примерно:

```json
{
  "event": "payment.waiting_for_capture",
  "object": {
    "id": "provider_payment_id",
    "status": "waiting_for_capture"
  }
}
```

### Какие модели использует

- `Payment`
- `PaymentEvent`
- `Reservation`
- `Rental`

### Что делает

1. Валидирует подпись webhook.
2. Находит `Payment` по `provider_payment_id`.
3. Создаёт `PaymentEvent`.
4. Переводит `Payment.status`.
5. При необходимости обновляет `Reservation.status`.

### Коды ошибок

- `400 INVALID_WEBHOOK_SIGNATURE`
- `404 PAYMENT_NOT_FOUND`
- `409 DUPLICATE_PROVIDER_EVENT`
- `500 PAYMENT_WEBHOOK_FAILED`

### Что отдаёт

```json
{
  "data": {
    "accepted": true
  }
}
```

## `GET /payments/:paymentId`

### Что принимает

- path: `paymentId`

### Какие модели использует

- `Payment`
- `PaymentEvent`

### Что делает

1. Находит платёж.
2. Проверяет доступ пользователя.
3. Возвращает текущий статус.

### Коды ошибок

- `401 UNAUTHORIZED`
- `404 PAYMENT_NOT_FOUND`
- `403 PAYMENT_FORBIDDEN`
- `500 PAYMENT_FETCH_FAILED`

### Что отдаёт

```json
{
  "data": {
    "payment": {
      "id": "uuid",
      "type": "preauth",
      "status": "authorized",
      "amount": 150000,
      "currency": "RUB",
      "failureCode": null,
      "failureMessage": null,
      "processedAt": "2026-03-24T10:00:00Z"
    }
  }
}
```

---

## 6. Аренда

## `GET /rentals/active`

### Кто вызывает

- mobile

### Что принимает

Ничего, кроме access token.

### Какие модели использует

- `Rental`
- `Reservation`
- `Product`
- `LockerLocation`

### Что делает

1. Находит текущую активную или ожидающую выдачи аренду пользователя.
2. Возвращает краткий summary для главного экрана.

### Коды ошибок

- `401 UNAUTHORIZED`
- `500 ACTIVE_RENTAL_FETCH_FAILED`

### Что отдаёт

```json
{
  "data": {
    "rental": {
      "id": "uuid",
      "status": "pickup_ready",
      "pickupPin": "4821",
      "plannedEndAt": "2026-03-25T12:00:00Z",
      "product": {
        "id": "uuid",
        "name": "Перфоратор Bosch"
      },
      "locker": {
        "id": "uuid",
        "name": "Постамат на Литейном",
        "address": "Санкт-Петербург, Литейный пр., 12"
      }
    }
  }
}
```

Если активной аренды нет:

```json
{
  "data": {
    "rental": null
  }
}
```

## `GET /rentals/:rentalId`

### Что принимает

- path: `rentalId`

### Какие модели использует

- `Rental`
- `RentalEvent`
- `Product`
- `LockerLocation`
- `Payment`
- `ConditionReport`

### Что делает

1. Находит аренду.
2. Проверяет доступ пользователя.
3. Собирает полный экран аренды.

### Коды ошибок

- `401 UNAUTHORIZED`
- `404 RENTAL_NOT_FOUND`
- `403 RENTAL_FORBIDDEN`
- `500 RENTAL_FETCH_FAILED`

### Что отдаёт

```json
{
  "data": {
    "rental": {
      "id": "uuid",
      "status": "active",
      "pickupPin": null,
      "startsAt": "2026-03-24T10:10:00Z",
      "plannedEndAt": "2026-03-25T10:10:00Z",
      "actualEndAt": null,
      "product": {
        "id": "uuid",
        "name": "Перфоратор Bosch",
        "coverUrl": "https://cdn.example.com/file.jpg"
      },
      "pickupLocker": {
        "id": "uuid",
        "name": "Постамат на Литейном",
        "address": "Санкт-Петербург, Литейный пр., 12"
      },
      "paymentSummary": {
        "preauthAmount": 150000,
        "capturedAmount": 0,
        "currency": "RUB"
      },
      "events": [
        {
          "id": "uuid",
          "eventType": "pickup_confirmed",
          "fromStatus": "pickup_ready",
          "toStatus": "active",
          "source": "locker_webhook",
          "createdAt": "2026-03-24T10:10:00Z"
        }
      ]
    }
  }
}
```

## `POST /rentals/:rentalId/start`

### Кто вызывает

- system
- internal admin tool

### Что принимает

```json
{
  "source": "locker_webhook",
  "eventId": "provider-event-id",
  "openedAt": "2026-03-24T10:10:00Z"
}
```

### Какие модели использует

- `Rental`
- `InventoryUnit`
- `LockerCell`
- `RentalEvent`

### Что делает

1. Проверяет, что аренда в `pickup_ready`.
2. Переводит аренду в `active`.
3. Ставит `starts_at`.
4. Переводит `InventoryUnit.status` в `rented`.
5. Создаёт `RentalEvent`.

### Коды ошибок

- `404 RENTAL_NOT_FOUND`
- `409 INVALID_RENTAL_STATUS`
- `409 DUPLICATE_RENTAL_START`
- `500 RENTAL_START_FAILED`

### Что отдаёт

```json
{
  "data": {
    "rental": {
      "id": "uuid",
      "status": "active",
      "startsAt": "2026-03-24T10:10:00Z"
    }
  }
}
```

## `POST /rentals/:rentalId/return-request`

### Кто вызывает

- mobile

### Что принимает

```json
{
  "lockerId": "uuid"
}
```

Если возврат только в постамат выдачи, `lockerId` можно не принимать.

### Какие модели использует

- `Rental`
- `LockerLocation`
- `LockerCell`
- `InventoryUnit`
- `RentalEvent`
- опционально `ReturnRequest`

### Что делает

1. Проверяет аренду.
2. Проверяет, что она в статусе `active` или `overdue`.
3. Находит доступную return-ячейку.
4. Открывает ячейку через ESI.
5. Переводит аренду в `return_in_progress`.
6. Создаёт событие.

### Коды ошибок

- `401 UNAUTHORIZED`
- `404 RENTAL_NOT_FOUND`
- `403 RENTAL_FORBIDDEN`
- `404 LOCKER_NOT_FOUND`
- `409 INVALID_RENTAL_STATUS`
- `409 RETURN_CELL_NOT_AVAILABLE`
- `409 LOCKER_OFFLINE`
- `502 ESI_OPEN_FAILED`
- `500 RETURN_REQUEST_FAILED`

### Что отдаёт

```json
{
  "data": {
    "return": {
      "rentalId": "uuid",
      "status": "return_in_progress",
      "lockerId": "uuid",
      "cellLabel": "A12",
      "instructions": "Откройте ячейку и положите товар внутрь"
    }
  }
}
```

## `POST /rentals/:rentalId/return-complete`

### Кто вызывает

- system
- internal admin tool

### Что принимает

```json
{
  "source": "locker_webhook",
  "eventId": "provider-event-id",
  "closedAt": "2026-03-25T09:55:00Z"
}
```

### Какие модели использует

- `Rental`
- `InventoryUnit`
- `LockerCell`
- `Payment`
- `RentalEvent`

### Что делает

1. Проверяет аренду.
2. Проверяет, что она в `return_in_progress`.
3. Переводит аренду в `completed`.
4. Ставит `actual_end_at` и `completed_at`.
5. Переводит `InventoryUnit.status` в `available` или `return_pending` по бизнес-правилу.
6. Выполняет `capture`, если он должен произойти в конце аренды.
7. Создаёт `RentalEvent`.

### Коды ошибок

- `404 RENTAL_NOT_FOUND`
- `409 INVALID_RENTAL_STATUS`
- `409 DUPLICATE_RETURN_COMPLETE`
- `502 PAYMENT_CAPTURE_FAILED`
- `500 RETURN_COMPLETE_FAILED`

### Что отдаёт

```json
{
  "data": {
    "rental": {
      "id": "uuid",
      "status": "completed",
      "actualEndAt": "2026-03-25T09:55:00Z",
      "completedAt": "2026-03-25T09:55:00Z"
    }
  }
}
```

---

## 7. История аренд

## `GET /me/rentals`

### Кто вызывает

- mobile

### Что принимает

Query params:

- `status`
- `page`
- `limit`

Допустимые `status`:

- `active`
- `completed`
- `cancelled`

### Какие модели использует

- `Rental`
- `Reservation`
- `Product`
- `LockerLocation`

### Что делает

1. Находит аренды пользователя.
2. Фильтрует по статусу.
3. Возвращает краткий список для экрана истории.

### Коды ошибок

- `401 UNAUTHORIZED`
- `400 INVALID_STATUS_FILTER`
- `500 RENTAL_HISTORY_FETCH_FAILED`

### Что отдаёт

```json
{
  "data": {
    "rentals": [
      {
        "id": "uuid",
        "status": "completed",
        "plannedEndAt": "2026-03-25T10:10:00Z",
        "actualEndAt": "2026-03-25T09:55:00Z",
        "product": {
          "id": "uuid",
          "name": "Перфоратор Bosch",
          "coverUrl": "https://cdn.example.com/file.jpg"
        },
        "locker": {
          "id": "uuid",
          "name": "Постамат на Литейном"
        }
      }
    ]
  },
  "meta": {
    "page": 1,
    "limit": 20,
    "total": 17
  }
}
```

## `GET /me/rentals/:rentalId`

### Что принимает

- path: `rentalId`

### Какие модели использует

- `Rental`
- `RentalEvent`
- `Payment`
- `Product`
- `LockerLocation`

### Что делает

1. Находит аренду пользователя.
2. Возвращает detail-экран истории.

По сути это пользовательская обёртка над `GET /rentals/:rentalId`.

### Коды ошибок

- `401 UNAUTHORIZED`
- `404 RENTAL_NOT_FOUND`
- `403 RENTAL_FORBIDDEN`
- `500 RENTAL_HISTORY_ITEM_FETCH_FAILED`

### Что отдаёт

Ответ можно держать таким же, как у:

- `GET /rentals/:rentalId`

---

## 8. Что ещё обязательно для P0, хотя это не весь public mobile API

Эти ручки тоже нужны для рабочего MVP:

- `POST /auth/request-code`
- `POST /auth/confirm-code`
- `POST /auth/refresh`
- `GET /me`
- `POST /me/verification`
- `GET /me/verification`
- `GET /cities`
- `POST /webhooks/esi`

Без них весь flow аренды не замкнётся.

---

## 9. Рекомендуемый порядок реализации

1. `POST /uploads/presign`
2. `GET /lockers`
3. `GET /lockers/:lockerId`
4. `GET /products`
5. `GET /products/:productId`
6. `GET /products/:productId/pricing`
7. `POST /reservations/quote`
8. `POST /reservations`
9. `GET /reservations/:reservationId`
10. `POST /payments/preauth`
11. `POST /payments/webhooks/yookassa`
12. `POST /reservations/:reservationId/confirm`
13. `GET /rentals/active`
14. `GET /rentals/:rentalId`
15. `POST /rentals/:rentalId/start`
16. `POST /rentals/:rentalId/return-request`
17. `POST /rentals/:rentalId/return-complete`
18. `GET /me/rentals`
19. `GET /me/rentals/:rentalId`

---

## 10. Важные бизнес-правила, которые надо заморозить до реализации

1. Возврат только в свой постамат или в любой?
2. Capture денег происходит в начале аренды или в конце?
3. Что делать, если предавторизация успешна, а ESI reserve не сработал?
4. Сколько живёт бронь?
5. Можно ли держать больше одной активной брони на пользователя?
6. Что считается доступностью: `available inventory unit` или `available locker cell + unit` одновременно?
