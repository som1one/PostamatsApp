# Модели приложения

Этот документ описывает доменные модели для приложения аренды товаров через
постаматы. Он нужен как основа для backend-схемы, API-контрактов и frontend DTO.

Документ сфокусирован на MVP, но структура сразу заложена так, чтобы не ломаться
при росте продукта.

## 1. Принципы моделирования

### Разделяем 3 уровня сущностей

- `каталог`: что за товар мы показываем пользователю
- `физическая единица`: конкретный экземпляр товара, который лежит в ячейке
- `операция аренды`: бронь, оплата, выдача, возврат

Это важно, потому что один `product` может иметь много физических единиц,
а одна физическая единица за жизнь проходит много аренд.

### Не смешиваем состояния

У приложения есть разные жизненные циклы:

- пользователь и верификация;
- постамат и ячейки;
- физический товар;
- бронь;
- платёж;
- аренда;
- инцидент.

У каждой области должен быть свой status, а не один общий "state".

### История изменений обязательна

Для MVP не обязательно делать event sourcing, но обязательно нужны:

- `created_at`
- `updated_at`
- `audit trail` для критичных действий
- история переходов аренды и платежей

## 2. Базовые поля

Почти у всех моделей должны быть:

- `id`
- `created_at`
- `updated_at`

Для мягкого удаления, где нужно:

- `deleted_at`

Для ссылок на пользователя или оператора:

- `created_by`
- `updated_by`

## 3. Модели пользователей и доступа

## 3.1 User

Основная клиентская сущность.

Поля:

- `id`
- `phone`
- `email`
- `first_name`
- `last_name`
- `middle_name`
- `birth_date`
- `preferred_city_id`
- `verification_status`
- `is_blocked`
- `blocked_reason`
- `last_login_at`
- `created_at`
- `updated_at`

Зачем нужна:

- вход в приложение;
- владение бронями, платежами и арендами;
- хранение статуса допуска к аренде.

Связи:

- `User 1 -> N VerificationRequest`
- `User 1 -> N Reservation`
- `User 1 -> N Payment`
- `User 1 -> N Rental`
- `User 1 -> N PushDevice`
- `User 1 -> N SupportIncident`

Индексы:

- уникальный по `phone`
- индекс по `verification_status`
- индекс по `preferred_city_id`

## 3.2 VerificationRequest

Хранит конкретную попытку верификации.

Поля:

- `id`
- `user_id`
- `status`
- `document_type`
- `document_number`
- `document_issue_date`
- `document_expiry_date`
- `front_file_id`
- `back_file_id`
- `selfie_file_id`
- `reviewed_by_admin_id`
- `reviewed_at`
- `reject_reason`
- `provider_name`
- `provider_check_id`
- `provider_payload_json`
- `created_at`
- `updated_at`

Статусы:

- `draft`
- `pending_review`
- `approved`
- `rejected`
- `blocked`

Зачем нужна:

- отделяет сам факт пользователя от его проверок;
- позволяет хранить историю повторных попыток.

## 3.3 AdminUser

Пользователь админки.

Поля:

- `id`
- `email`
- `phone`
- `password_hash`
- `full_name`
- `role`
- `is_active`
- `last_login_at`
- `created_at`
- `updated_at`

Роли для MVP:

- `super_admin`
- `operator`

Роли после MVP:

- `franchise_admin`
- `support_agent`
- `finance`

## 3.4 PushDevice

Устройство для push-уведомлений.

Поля:

- `id`
- `user_id`
- `platform`
- `push_token`
- `app_version`
- `device_name`
- `last_seen_at`
- `created_at`
- `updated_at`

## 4. Файлы и медиа

## 4.1 MediaFile

Универсальная модель файлов.

Поля:

- `id`
- `storage_provider`
- `bucket`
- `file_key`
- `mime_type`
- `file_size`
- `original_name`
- `kind`
- `uploaded_by_user_id`
- `uploaded_by_admin_id`
- `created_at`

Виды `kind`:

- `verification_front`
- `verification_back`
- `verification_selfie`
- `product_cover`
- `product_gallery`
- `incident_attachment`
- `condition_photo_before`
- `condition_photo_after`

Зачем нужна:

- единая точка для документов, фото товара и инцидентов.

## 5. География и постаматы

## 5.1 City

Поля:

- `id`
- `name`
- `slug`
- `timezone`
- `is_active`
- `sort_order`
- `created_at`
- `updated_at`

Зачем нужна:

- фильтрация каталога;
- выбор стартового города;
- масштабирование по городам.

## 5.2 LockerLocation

Точка постамата.

Поля:

- `id`
- `city_id`
- `name`
- `address`
- `lat`
- `lon`
- `status`
- `working_hours_json`
- `external_provider`
- `external_locker_id`
- `partner_name`
- `last_online_at`
- `created_at`
- `updated_at`

Статусы:

- `online`
- `offline`
- `maintenance`
- `degraded`

Зачем нужна:

- карта;
- выбор точки выдачи;
- отображение доступности товара по локациям.

Связи:

- `City 1 -> N LockerLocation`
- `LockerLocation 1 -> N LockerCell`

## 5.3 LockerCell

Конкретная ячейка внутри постамата.

Поля:

- `id`
- `locker_id`
- `external_cell_id`
- `label`
- `size`
- `status`
- `supports_return`
- `last_opened_at`
- `last_closed_at`
- `last_event_at`
- `created_at`
- `updated_at`

Статусы:

- `vacant`
- `occupied`
- `reserved`
- `opened`
- `fault`
- `disabled`

Зачем нужна:

- связь между физическим товаром и ячейкой;
- управление выдачей и возвратом;
- обработка событий от ESI API.

## 6. Каталог

## 6.1 ProductCategory

Поля:

- `id`
- `name`
- `slug`
- `sort_order`
- `is_active`
- `created_at`
- `updated_at`

## 6.2 Product

Карточка товара в каталоге.

Поля:

- `id`
- `category_id`
- `name`
- `slug`
- `short_description`
- `full_description`
- `specs_json`
- `rules_text`
- `kit_description`
- `brand`
- `cover_file_id`
- `is_active`
- `created_at`
- `updated_at`

Зачем нужна:

- пользователь видит именно Product;
- это SKU-уровень, а не физический экземпляр.

Связи:

- `ProductCategory 1 -> N Product`
- `Product 1 -> N ProductImage`
- `Product 1 -> N InventoryUnit`
- `Product 1 -> N PricePlan`

## 6.3 ProductImage

Галерея товара.

Поля:

- `id`
- `product_id`
- `file_id`
- `sort_order`
- `created_at`

## 6.4 ProductAttribute

Опциональная модель для удобной фильтрации.

Поля:

- `id`
- `product_id`
- `name`
- `value`
- `unit`
- `sort_order`

Для MVP можно хранить характеристики в `specs_json`, но если фильтров станет
много, эту модель лучше вынести.

## 7. Физические единицы товара

## 7.1 InventoryUnit

Физический экземпляр товара.

Поля:

- `id`
- `product_id`
- `locker_cell_id`
- `serial_number`
- `barcode`
- `status`
- `condition_grade`
- `condition_note`
- `purchase_price`
- `purchase_date`
- `last_check_at`
- `created_at`
- `updated_at`

Статусы:

- `available`
- `reserved`
- `rented`
- `return_pending`
- `damaged`
- `maintenance`
- `lost`
- `retired`

Зачем нужна:

- это объект, который реально переходит из ячейки в аренду и обратно.

Связи:

- `InventoryUnit N -> 1 Product`
- `InventoryUnit N -> 1 LockerCell`
- `InventoryUnit 1 -> N InventoryMovement`
- `InventoryUnit 1 -> N Rental`

## 7.2 InventoryMovement

История перемещений и смены статусов физической единицы.

Поля:

- `id`
- `inventory_unit_id`
- `from_locker_id`
- `to_locker_id`
- `from_cell_id`
- `to_cell_id`
- `from_status`
- `to_status`
- `reason`
- `comment`
- `performed_by_admin_id`
- `created_at`

Зачем нужна:

- аудит;
- расследование потерь и поломок;
- понимание истории товара.

## 7.3 ConditionReport

Фиксация состояния товара.

Поля:

- `id`
- `inventory_unit_id`
- `rental_id`
- `report_type`
- `condition_grade`
- `note`
- `created_by_user_id`
- `created_by_admin_id`
- `created_at`

Типы:

- `before_pickup`
- `after_return`
- `incident_review`

Связи:

- `ConditionReport 1 -> N ConditionReportPhoto`

## 7.4 ConditionReportPhoto

Поля:

- `id`
- `condition_report_id`
- `file_id`
- `sort_order`
- `created_at`

## 8. Тарифы и цены

## 8.1 PricePlan

Описывает доступный тариф.

Поля:

- `id`
- `product_id`
- `name`
- `duration_type`
- `duration_value`
- `base_amount`
- `currency`
- `is_active`
- `sort_order`
- `created_at`
- `updated_at`

Примеры:

- `1 day`
- `2 days`
- `3 days`

Для MVP достаточно этой модели.

### После MVP можно добавить PriceRule

Если появятся:

- скидки;
- сезонные цены;
- цены по городам;
- цены по точкам;
- почасовая аренда.

Тогда вводится `PriceRule` с более сложной логикой.

## 9. Бронирование

## 9.1 Reservation

Бронь до начала аренды.

Поля:

- `id`
- `user_id`
- `product_id`
- `inventory_unit_id`
- `locker_id`
- `price_plan_id`
- `status`
- `duration_type`
- `duration_value`
- `quoted_amount`
- `preauth_amount`
- `expires_at`
- `confirmed_at`
- `cancelled_at`
- `cancel_reason`
- `created_at`
- `updated_at`

Статусы:

- `created`
- `awaiting_payment`
- `payment_authorized`
- `confirmed`
- `expired`
- `cancelled`

Зачем нужна:

- фиксирует намерение аренды;
- держит цену и товар до перехода в аренду.

Связи:

- `Reservation N -> 1 User`
- `Reservation N -> 1 Product`
- `Reservation N -> 1 InventoryUnit`
- `Reservation N -> 1 LockerLocation`
- `Reservation N -> 1 PricePlan`
- `Reservation 1 -> N Payment`
- `Reservation 1 -> 1 Rental`

## 9.2 ReservationQuote

Снапшот расчёта цены до создания брони.

Поля:

- `id`
- `user_id`
- `product_id`
- `locker_id`
- `price_plan_id`
- `amount`
- `preauth_amount`
- `currency`
- `expires_at`
- `payload_json`
- `created_at`

Для MVP можно вообще не хранить как таблицу, если quote нужен только как
промежуточный ответ API. Но если нужна трассировка расчётов, модель полезна.

## 10. Платежи

## 10.1 Payment

Факт платёжной операции.

Поля:

- `id`
- `user_id`
- `reservation_id`
- `rental_id`
- `provider`
- `provider_payment_id`
- `payment_method_id`
- `type`
- `status`
- `amount`
- `currency`
- `failure_code`
- `failure_message`
- `processed_at`
- `created_at`
- `updated_at`

Типы:

- `preauth`
- `capture`
- `cancel`
- `refund`
- `extra_charge`

Статусы:

- `created`
- `pending`
- `authorized`
- `captured`
- `cancelled`
- `failed`
- `refunded`

Зачем нужна:

- отделяет бизнес-аренду от конкретных операций платёжного провайдера.

## 10.2 PaymentMethod

Сохранённый способ оплаты пользователя.

Поля:

- `id`
- `user_id`
- `provider`
- `provider_method_id`
- `masked_pan`
- `card_brand`
- `expires_at`
- `is_default`
- `created_at`
- `updated_at`

Для MVP может быть опциональной, если сначала достаточно одноразового сценария.

## 10.3 PaymentEvent

Техническая история платёжных webhook и переходов.

Поля:

- `id`
- `payment_id`
- `provider_event_id`
- `event_type`
- `payload_json`
- `received_at`

Зачем нужна:

- дебаг;
- расследование споров;
- повторная обработка проблемных webhook.

## 11. Аренда

## 11.1 Rental

Главная операционная модель продукта.

Поля:

- `id`
- `user_id`
- `reservation_id`
- `inventory_unit_id`
- `pickup_locker_id`
- `return_locker_id`
- `pickup_pin`
- `status`
- `starts_at`
- `planned_end_at`
- `actual_end_at`
- `overdue_started_at`
- `completed_at`
- `created_at`
- `updated_at`

Статусы:

- `pickup_ready`
- `pickup_opened`
- `active`
- `return_in_progress`
- `completed`
- `overdue`
- `incident`
- `cancelled`

Зачем нужна:

- это основная бизнес-сущность системы;
- именно вокруг неё строятся экраны активной аренды, возврата и истории.

Связи:

- `Rental N -> 1 User`
- `Rental N -> 1 Reservation`
- `Rental N -> 1 InventoryUnit`
- `Rental N -> 1 LockerLocation`
- `Rental 1 -> N RentalEvent`
- `Rental 1 -> N Payment`
- `Rental 1 -> N SupportIncident`
- `Rental 1 -> N ConditionReport`

## 11.2 RentalEvent

История жизненного цикла аренды.

Поля:

- `id`
- `rental_id`
- `event_type`
- `from_status`
- `to_status`
- `source`
- `payload_json`
- `created_at`

Источники:

- `system`
- `user`
- `admin`
- `payment_webhook`
- `locker_webhook`

Зачем нужна:

- debugging;
- таймлайн в админке;
- расследование инцидентов.

## 11.3 ReturnRequest

Явное намерение пользователя вернуть товар.

Поля:

- `id`
- `rental_id`
- `locker_id`
- `status`
- `requested_at`
- `opened_at`
- `closed_at`
- `failed_reason`
- `created_at`
- `updated_at`

Статусы:

- `created`
- `locker_opened`
- `awaiting_close`
- `completed`
- `failed`

Для MVP эту модель можно заменить полями в `Rental`, но отдельная сущность
делает возврат чище.

## 12. Инциденты и поддержка

## 12.1 SupportIncident

Инцидент по аренде, платежу или постамату.

Поля:

- `id`
- `user_id`
- `rental_id`
- `locker_id`
- `type`
- `status`
- `priority`
- `title`
- `description`
- `resolved_by_admin_id`
- `resolved_at`
- `created_at`
- `updated_at`

Типы:

- `locker_open_failed`
- `locker_close_failed`
- `item_damaged`
- `item_incomplete`
- `payment_issue`
- `locker_offline`
- `other`

Статусы:

- `new`
- `in_progress`
- `waiting_user`
- `resolved`
- `closed`

## 12.2 SupportIncidentAttachment

Поля:

- `id`
- `incident_id`
- `file_id`
- `created_at`

## 13. Интеграции и системные журналы

## 13.1 LockerEventLog

Сырые события от постамата.

Поля:

- `id`
- `locker_id`
- `cell_id`
- `provider`
- `provider_event_id`
- `event_type`
- `payload_json`
- `received_at`
- `processed_at`
- `process_status`

Зачем нужна:

- не терять первичный сигнал от железа;
- уметь переиграть обработку.

## 13.2 IntegrationJob

Фоновые задания на retry.

Поля:

- `id`
- `kind`
- `payload_json`
- `status`
- `attempt_count`
- `next_run_at`
- `last_error`
- `created_at`
- `updated_at`

## 14. Минимальные enum для MVP

### verification_status

- `draft`
- `pending_review`
- `approved`
- `rejected`
- `blocked`

### locker_status

- `online`
- `offline`
- `maintenance`
- `degraded`

### locker_cell_status

- `vacant`
- `occupied`
- `reserved`
- `opened`
- `fault`
- `disabled`

### inventory_status

- `available`
- `reserved`
- `rented`
- `return_pending`
- `damaged`
- `maintenance`
- `lost`
- `retired`

### reservation_status

- `created`
- `awaiting_payment`
- `payment_authorized`
- `confirmed`
- `expired`
- `cancelled`

### payment_status

- `created`
- `pending`
- `authorized`
- `captured`
- `cancelled`
- `failed`
- `refunded`

### rental_status

- `pickup_ready`
- `pickup_opened`
- `active`
- `return_in_progress`
- `completed`
- `overdue`
- `incident`
- `cancelled`

### incident_status

- `new`
- `in_progress`
- `waiting_user`
- `resolved`
- `closed`

## 15. Связи моделей в кратком виде

- `City 1 -> N LockerLocation`
- `LockerLocation 1 -> N LockerCell`
- `ProductCategory 1 -> N Product`
- `Product 1 -> N ProductImage`
- `Product 1 -> N InventoryUnit`
- `Product 1 -> N PricePlan`
- `LockerCell 1 -> 0..1 InventoryUnit`
- `User 1 -> N VerificationRequest`
- `User 1 -> N Reservation`
- `User 1 -> N Payment`
- `User 1 -> N Rental`
- `Reservation 1 -> N Payment`
- `Reservation 1 -> 0..1 Rental`
- `InventoryUnit 1 -> N Rental`
- `Rental 1 -> N RentalEvent`
- `Rental 1 -> N SupportIncident`
- `Rental 1 -> N ConditionReport`

## 16. Что можно упростить в MVP

Для очень быстрого запуска можно не выносить в отдельные таблицы:

- `ProductAttribute`
- `ReservationQuote`
- `PaymentMethod`
- `ReturnRequest`
- `SupportIncidentAttachment`

Их можно временно хранить:

- в `json` полях;
- как derived-данные;
- или вообще не хранить на первом релизе.

## 17. Что нельзя упрощать

Эти модели обязательно должны быть выделены отдельно:

- `User`
- `VerificationRequest`
- `City`
- `LockerLocation`
- `LockerCell`
- `Product`
- `InventoryUnit`
- `PricePlan`
- `Reservation`
- `Payment`
- `Rental`
- `RentalEvent`

Без них начнёт смешиваться каталог, физический товар, оплата и жизненный цикл аренды.

## 18. Что я бы добавил сразу после MVP

- `Franchise`
- `FranchiseCityAccess`
- `PromoCode`
- `TariffRule`
- `OverdueCharge`
- `NotificationLog`
- `AuditLog`
- `Review`

## 19. Рекомендация по реализации

Если делать трезво и без лишнего перегруза, я бы начинал с такого ядра:

1. `User`
2. `VerificationRequest`
3. `City`
4. `LockerLocation`
5. `LockerCell`
6. `ProductCategory`
7. `Product`
8. `InventoryUnit`
9. `PricePlan`
10. `Reservation`
11. `Payment`
12. `Rental`
13. `RentalEvent`
14. `SupportIncident`

Этого достаточно, чтобы:

- собрать API;
- построить frontend;
- провести реальную аренду;
- отследить ошибки;
- не сломать предметную модель на первой же неделе.
