# Requirements Document

## Introduction

Привести мобильное приложение Naprokatberu (Expo / React Native, iOS + Android) к
паритету с веб-фронтендом (`web/`) по визуальному языку и пользовательским
сценариям. Веб уже реализует полный путь аренды через постаматы: каталог,
карточка товара с календарём дат, выбор постамата на карте, чекаут с шагами,
оплата через ЮKassa (с временным dev-bypass через `confirmReservation`),
история бронирований и аренд (`/profile/orders`), запрос возврата через
постамат, верификация документов, статичные страницы (FAQ, Идеи, О сервисе,
Условия аренды), профиль с редактированием имени и e-mail, аутентификация по
телефону через SMS / звонок.

Сейчас мобильное приложение использует собственный визуальный язык
(бордовая/песочная палитра, кастомные SVG-иконки) и реализует только базовую
часть потока: каталог, простую бронь без календаря и шагов, карту без
react-native-maps в продакшене, профиль без редактирования, без истории заказов
и без возврата.

В рамках этой фичи мобильное приложение должно:

1. Перенять визуальный язык веба (палитра, типографика, статус-пиллы,
   карточки, OrderSummary, кнопки, формы) с учётом mobile-native паттернов
   (bottom-sheet, native pickers, swipe).
2. Использовать те же API-эндпоинты и структуры данных, что и веб
   (`web/src/shared/api/types.ts`).
3. Реализовать полный путь аренды: вход → каталог → карточка товара с
   календарём → выбор постамата → чекаут с шагами → оплата ЮKassa в
   браузере / WebView → возврат в приложение → активная аренда → запрос
   возврата.
4. Поддерживать пять разделов в bottom-nav: Главная, Каталог, Карта,
   Мои заказы, Профиль.
5. Поддерживать deep links и universal links для карточки товара, брони и
   возврата с оплаты, а также push-уведомления (Expo Notifications) для
   ключевых событий.

Цель — единый продукт, в котором пользователь может выбрать, забрать и вернуть
любую вещь через постамат с того же визуала и логики, что и на сайте.

## Glossary

- **Mobile_App** — приложение на Expo / React Native, целевые платформы iOS и
  Android, кодовая база в `mobile/`.
- **Web_App** — действующий веб-фронтенд в `web/` (Next.js), эталон по дизайну
  и сценариям.
- **Backend_API** — действующий REST API в `backend/`, общий для веба,
  мобайла и админки.
- **Design_Language** — набор визуальных правил и компонентов веба: палитра
  (`--danger #dd362d`, фоновые/текстовые токены), типографика, отступы, формы
  кнопок, карточек, статус-пиллов, OrderSummary, RentalDateRangePicker.
- **Native_Pattern** — мобильный UI-паттерн (bottom-sheet, swipe, native date
  picker, system status bar, safe-area), допустимый при адаптации
  Design_Language.
- **City** — город из `/cities/`, объект с полями `id`, `name`, `slug`,
  `timezone`, `isActive`, `sortOrder`.
- **Locker** — постамат из `/lockers/`, с координатами, статусом
  (`online`/`offline`/`maintenance`/`degraded`), адресом и счётчиками
  доступности.
- **Product** — товар каталога; имеет `priceFrom`, набор `pricePlans`,
  изображения, описание, комплект, доступные постаматы.
- **Reservation** — бронь, состояния: `created`, `awaiting_payment`,
  `payment_authorized`, `cancelled`, `expired`, `confirmed`.
- **Rental** — активная аренда, состояния: `pickup_ready`, `pickup_opened`,
  `active`, `overdue`, `return_in_progress`, `completed`, `cancelled`.
- **Verification_Status** — статус KYC: `none`, `pending`, `approved`,
  `rejected`.
- **Auth_Code_Channel** — канал доставки кода: `sms` или `call`
  (последние 4 цифры входящего номера).
- **Yookassa_Payment_Flow** — оформление оплаты ЮKassa: открытие платёжной
  страницы во внешнем браузере (или WebView) и возврат в приложение по
  deep link `naprokatberu://payment/return` или universal link.
- **Deep_Link** — ссылка вида `naprokatberu://...` или universal link
  `https://naprokatberu.ru/...`, открывающаяся в Mobile_App.
- **Push_Notification** — пуш через Expo Notifications для ключевых событий
  (бронь оплачена, бронь скоро истечёт, аренда скоро заканчивается, постамат
  готов к выдаче, документы проверены).

## Requirements

### Requirement 1: Визуальное соответствие веб-дизайну

**User Story:** Как пользователь, я хочу, чтобы мобильное приложение
выглядело узнаваемо так же, как сайт, чтобы я не сомневался, что это один и
тот же сервис, и сразу понимал интерфейс.

#### Acceptance Criteria

1. THE Mobile_App SHALL использовать палитру, заданную в Design_Language
   веба: акцентный цвет `#dd362d`, нейтральные фоны и текстовые токены,
   совпадающие с переменными `globals.css` веба.
2. THE Mobile_App SHALL использовать те же названия и иерархию визуальных
   компонентов, что и Web_App: `Surface`, `Button` (`primary`, `secondary`,
   `ghost`, `dark`), `StatusPill`, `EmptyState`, `PageHeader`,
   `OrderSummary`, `ProductCard`, `LockerCard`, `RentalDateRangePicker`,
   `RentalDurationSelector`, `CategoryTabs`.
3. THE Mobile_App SHALL использовать набор иконок lucide (через
   `lucide-react-native` или эквивалент) с теми же именами иконок, что и
   Web_App (`MapPinned`, `PackageCheck`, `ShieldCheck`, `Boxes`, `Filter`,
   `Search`, `ArrowLeft`, `RotateCcw`, `CreditCard`, `XCircle`,
   `Clock3`, `AlertTriangle`, `CheckCircle2`, `LogOut`, `UserRound`,
   `FileCheck2`).
4. WHERE Native_Pattern даёт лучший UX, чем прямой перенос веб-разметки,
   THE Mobile_App SHALL применить Native_Pattern (bottom-sheet вместо
   модального overlay, system date picker вместо HTML-инпутов,
   native swipe-to-go-back), сохраняя при этом палитру, типографику и
   текстовые ярлыки Web_App.
5. IF Native_Pattern не даёт UX-выигрыша по сравнению с переносом
   веб-разметки 1:1, THEN THE Mobile_App SHALL воспроизводить структуру
   и компоненты Web_App без замены на нативный паттерн.
6. THE Mobile_App SHALL отрисовывать каждый экран на iOS и Android с учётом
   safe-area (верхний и нижний insets) без перекрытия контента системными
   барами.
7. THE Mobile_App SHALL использовать русскую локализацию текстов, идентичную
   текстам Web_App для тех же экранов (заголовки, кнопки, пустые состояния,
   ошибки).

### Requirement 2: Структура навигации и bottom-nav

**User Story:** Как пользователь, я хочу понятную нижнюю навигацию, чтобы
быстро переключаться между основными разделами.

#### Acceptance Criteria

1. THE Mobile_App SHALL отображать постоянную нижнюю навигацию из пяти
   вкладок в фиксированном порядке: «Главная», «Каталог», «Карта»,
   «Мои заказы», «Профиль».
2. WHEN пользователь нажимает на вкладку нижней навигации, THE Mobile_App
   SHALL открыть соответствующий стек экранов и сохранить состояние
   остальных стеков (выбранный товар, фильтры, скролл).
3. WHILE Reservation в статусе `created`, `awaiting_payment` или
   `payment_authorized` существует у пользователя, THE Mobile_App SHALL
   показывать на вкладке «Мои заказы» бейдж с количеством активных броней
   и аренд.
4. WHILE пользователь не аутентифицирован, THE Mobile_App SHALL показывать
   все вкладки и при попытке открыть «Мои заказы» или «Профиль» открывать
   экран входа без потери выбранной вкладки.
5. THE Mobile_App SHALL использовать на каждой вкладке внутренний стек
   экранов (например, Каталог → Карточка товара → Выбор постамата →
   Чекаут) с поддержкой системного жеста «Назад» на iOS и аппаратной
   кнопки «Назад» на Android.

### Requirement 3: Аутентификация по телефону

**User Story:** Как пользователь, я хочу войти в мобильное приложение
по номеру телефона, как на сайте, чтобы попасть в свой аккаунт без пароля.

#### Acceptance Criteria

1. THE Mobile_App SHALL запрашивать у пользователя номер телефона в формате
   РФ (+7) или РБ (+375) с теми же правилами нормализации, что и Web_App
   (`normalizePhoneInput`, `normalizePhoneForApi`).
2. WHEN пользователь подтверждает ввод номера, THE Mobile_App SHALL
   вызывать `POST /auth/request-code` с нормализованным номером и
   сохранять `verificationSessionId` и `ttlSeconds` из ответа.
3. WHEN Backend_API возвращает Auth_Code_Channel `call`, THE Mobile_App
   SHALL показывать инструкцию о входящем звонке и поле для ввода
   последних 4 цифр номера, с которого звонят.
4. WHEN Backend_API возвращает Auth_Code_Channel `sms`, THE Mobile_App
   SHALL показывать поле для ввода 4-значного SMS-кода с поддержкой
   автозаполнения (`autoComplete=one-time-code` на iOS, SMS Retriever или
   `autoComplete=sms-otp` на Android).
5. WHILE `ttlSeconds > 0` после запроса кода, THE Mobile_App SHALL
   показывать обратный отсчёт до следующей возможности повторно запросить
   код.
6. WHEN пользователь отправляет код, THE Mobile_App SHALL вызывать
   `POST /auth/confirm-code` с `verificationSessionId` и кодом, и при
   успехе сохранять `accessToken` и `refreshToken` в безопасное хранилище
   (`expo-secure-store` на iOS Keychain и Android Keystore).
7. IF `POST /auth/confirm-code` возвращает ошибку с кодом из
   `AUTH_ERROR_MESSAGES` (Web_App), THEN THE Mobile_App SHALL показать тот
   же текст ошибки, что и Web_App, в общей плашке `alert-danger`.
8. WHEN `accessToken` истекает в течение сессии и Backend_API возвращает
   401, THE Mobile_App SHALL вызвать `POST /auth/refresh` c сохранённым
   `refreshToken` и повторить исходный запрос один раз.
9. IF `POST /auth/refresh` возвращает ошибку, THEN THE Mobile_App SHALL
   очистить токены, локальное состояние пользователя и открыть экран входа.
10. WHEN пользователь нажимает «Выйти» в Профиле, THE Mobile_App SHALL
    вызвать `POST /auth/logout` с `accessToken`, очистить токены и
    локальное состояние пользователя, и открыть экран входа.

### Requirement 4: Главная страница

**User Story:** Как пользователь, я хочу видеть на главной все ключевые
точки входа: текущая бронь / аренда, популярные товары, постаматы рядом, как
на сайте.

#### Acceptance Criteria

1. THE Mobile_App SHALL отображать на Главной hero-блок с эйбрау «аренда
   через постаматы», заголовком и кнопкой «Начать аренду», ведущей в
   Каталог, и кнопкой «Карта постаматов», ведущей в Карту.
2. THE Mobile_App SHALL загружать список Cities через `GET /cities/` и
   показывать селектор города в hero-блоке Главной с теми же правилами
   восстановления (`readSavedCityId`, `resolveSelectedCityId`,
   `saveSelectedCityId`), что и Web_App.
3. WHEN выбран City, THE Mobile_App SHALL загружать через
   `GET /products?cityId=...&availableOnly=true` первые 6 Products и
   показывать их в горизонтальном списке «Популярные» с теми же ценами
   и метками наличия, что и Web_App.
4. WHEN у пользователя есть активный Reservation или Rental, THE Mobile_App
   SHALL показывать на Главной блок «Текущая аренда» с обложкой товара,
   адресом постамата и дедлайном (бронь оплачена / истекает через X /
   просрочено), используя ту же логику расчёта, что
   `getReservationDeadlineMeta` и `getRentalDeadlineMeta` Web_App.
5. WHILE у пользователя нет активного Reservation и Rental, THE Mobile_App
   SHALL показывать в блоке «Текущая аренда» пустое состояние с эйбрау
   «Аренды пока нет» и кнопкой «Открыть каталог», и одновременно
   показывать ниже блок «Постаматы рядом» со списком первых 6 Lockers
   выбранного City.
6. WHEN пользователь нажимает «Открыть весь каталог» или ссылку «Карта»
   на Главной, THE Mobile_App SHALL переходить во вкладку Каталог или
   Карта без потери состояния выбранного City.
7. THE Mobile_App SHALL показывать в стат-блоке Главной четыре метрики
   (количество городов, постаматов, пользователей, товаров) с теми же
   подписями, что и Web_App, через `GET /public/stats` и
   `GET /lockers/`.

### Requirement 5: Каталог товаров

**User Story:** Как пользователь, я хочу искать товары и фильтровать по
городу, категории и наличию, как на сайте.

#### Acceptance Criteria

1. THE Mobile_App SHALL отображать в Каталоге селектор города, поиск,
   тумблер «Только доступные» и список категорий, источники данных и
   правила формирования категорий — те же, что в `CatalogClient` Web_App.
2. WHEN пользователь меняет любой из фильтров (City, search, categoryId,
   availableOnly), THE Mobile_App SHALL вызывать
   `GET /products?cityId=...&search=...&availableOnly=...&limit=100` и
   обновлять список ProductCard в сетке.
3. WHILE загружается список Products, THE Mobile_App SHALL показывать
   skeleton-плейсхолдеры в количестве не менее 6 элементов.
4. IF список Products пуст после применения фильтров, THEN THE Mobile_App
   SHALL показать `EmptyState` с заголовком «Товаров не найдено» и
   подсказкой о смене города или категории.
5. THE Mobile_App SHALL открывать экран фильтров в виде bottom-sheet с
   полями «Поиск», «Только доступные» и `CategoryTabs`, и кнопками
   «Сбросить» и «Применить», аналогично `catalog-filter-sheet` Web_App.
6. WHEN пользователь нажимает на ProductCard, THE Mobile_App SHALL
   открывать экран карточки товара по `slug` или `id` через
   `resolveProductBySlugOrId`.

### Requirement 6: Карточка товара и календарь аренды

**User Story:** Как пользователь, я хочу выбрать срок и постамат и увидеть
итоговую цену, как на сайте.

#### Acceptance Criteria

1. THE Mobile_App SHALL загружать ProductDetail через тот же набор данных,
   что Web_App (`resolveProductBySlugOrId`), и показывать галерею,
   название, бренд, описание, комплект, инструкции, OrderSummary.
2. THE Mobile_App SHALL показывать описание товара с кнопкой
   «Показать полностью» / «Свернуть», когда длина текста превышает
   `PRODUCT_DESCRIPTION_TOGGLE_THRESHOLD` (140 символов), как Web_App.
3. THE Mobile_App SHALL отображать `RentalDateRangePicker` для выбора
   диапазона дат с теми же правилами `daysBetweenInclusive`, и показывать
   расчётную сумму и процент скидки по тем же формулам, что и Web_App.
4. WHEN у Product есть `pricePlans` с `durationType=day`, THE Mobile_App
   SHALL показывать `RentalDurationSelector` с готовыми тарифами и при
   выборе плана выставлять `endDate = startDate + plan.durationValue`.
5. THE Mobile_App SHALL показывать список доступных Lockers выбранного
   City, в том числе через карту react-native-maps, и отмечать выбранный
   Locker. Lockers без `lat`/`lon` SHALL показываться только в списке.
6. WHEN пользователь меняет Locker, тариф или даты, THE Mobile_App SHALL
   запрашивать `GET /products/{id}/pricing?lockerId=...&durationType=...&durationValue=...`
   и обновлять OrderSummary.
7. IF запрос pricing завершается ошибкой, THEN THE Mobile_App SHALL
   показать в OrderSummary плашку «Цена уточнится при оформлении.
   Проверьте доступность постамата.» аналогично Web_App.
8. WHEN пользователь нажимает «Перейти к оформлению» при выбранных
   Product, Locker, плане и дате, THE Mobile_App SHALL открывать экран
   Чекаута с теми же query-параметрами (`productId`, `lockerId`,
   `durationType`, `durationValue`, `startAt`, опциональный
   `reservationId` для переноса).

### Requirement 7: Чекаут и оплата ЮKassa

**User Story:** Как пользователь, я хочу пройти оплату ЮKassa из мобильного
приложения и автоматически вернуться в карточку аренды.

#### Acceptance Criteria

1. THE Mobile_App SHALL показывать экран Чекаута с шагами «Параметры
   аренды», «Постамат», «Сводка и оплата», аналогичными шагам
   `CheckoutClient` Web_App.
2. WHEN пользователь подтверждает заказ на Чекауте, THE Mobile_App SHALL
   вызывать `POST /reservations` с теми же полями, что и Web_App, и
   получать Reservation с `id`, `status`, `expiresAt`.
3. WHEN Reservation создан, THE Mobile_App SHALL запускать
   Yookassa_Payment_Flow: открывать платёжную страницу в системном
   браузере или WebView, передавая `return_url` со схемой
   `naprokatberu://payment/return?reservationId={reservationId}`.
4. WHEN Backend_API временно работает в режиме dev-bypass (Yookassa
   отключён), THE Mobile_App SHALL отправлять `POST /reservations/{id}/confirm`
   и сразу переходить к карточке аренды, как Web_App в текущей версии
   (`handlePay`).
5. WHEN Mobile_App получает Deep_Link `naprokatberu://payment/return`,
   THE Mobile_App SHALL запросить `GET /reservations/{id}` и открыть
   экран «Возврат с оплаты» с состоянием `success`, `pending` или
   `error` в зависимости от `reservation.status`, аналогично
   `PaymentReturnClient` Web_App.
6. IF Reservation не оплачен через 15 минут после создания, THEN THE
   Mobile_App SHALL показывать на карточке заказа статус-пилюлю
   `expired` и не предлагать «Оплатить».
7. IF `POST /reservations` возвращает ошибку `LOCKER_OFFLINE`,
   `LOCKER_NOT_CONFIGURED`, `ESI_RESERVE_FAILED` или `ESI_HTTP_ERROR`,
   THEN THE Mobile_App SHALL показать тот же русский текст, что Web_App
   (`handlePay` в `RentalsClient`), и оставить пользователя на Чекауте.

### Requirement 8: Карта постаматов

**User Story:** Как пользователь, я хочу видеть постаматы на карте и
переходить к их товарам.

#### Acceptance Criteria

1. THE Mobile_App SHALL использовать `react-native-maps` (Apple Maps на
   iOS, Google Maps на Android) и отображать все Lockers выбранного City
   с координатами `lat` и `lon`.
2. THE Mobile_App SHALL запрашивать у пользователя разрешение на
   геолокацию через `expo-location` с обоснованием
   `locationWhenInUsePermission` (`app.json`) и при выдаче разрешения
   показывать его положение на карте.
3. WHEN геолокация доступна и в City нет сохранённого выбора, THE
   Mobile_App SHALL автоматически выбирать ближайший к пользователю City
   (через `findNearestCityIdByLockers`).
4. WHEN пользователь нажимает на маркер Locker, THE Mobile_App SHALL
   показывать карточку с названием, адресом, статусом и кнопками
   «Каталог постамата» (открыть Каталог с фильтром по `lockerId`) и
   «Подробнее» (открыть экран Locker).
5. IF City не имеет ни одного Locker с координатами, THEN THE Mobile_App
   SHALL показывать только список Lockers без карты с EmptyState
   «Постаматы не найдены».
6. THE Mobile_App SHALL показывать статус Locker
   (`online`/`offline`/`maintenance`/`degraded`) в виде StatusPill с
   цветами, совпадающими с Web_App.

### Requirement 9: Мои заказы (брони и аренды)

**User Story:** Как пользователь, я хочу видеть все свои будущие брони,
активные аренды и историю в одном месте, как на сайте.

#### Acceptance Criteria

1. THE Mobile_App SHALL загружать одновременно `GET /me/reservations` и
   `GET /me/rentals?status=...` и показывать их в одной сетке, разделяя
   на «Будущие брони» и «Аренды», как `RentalsClient` Web_App.
2. THE Mobile_App SHALL показывать фильтр «Все / Активные / Завершённые /
   Отменённые», передавая параметр `status` в `GET /me/rentals`.
3. THE Mobile_App SHALL пересчитывать дедлайны раз в 60 секунд и обновлять
   плашки `rental-deadline` (`warn`, `danger`, `success`) с заголовками,
   совпадающими с Web_App (`getReservationDeadlineMeta` и
   `getRentalDeadlineMeta`).
4. WHEN Reservation в статусе `created` или `awaiting_payment`, THE
   Mobile_App SHALL показывать на её карточке кнопку «Оплатить»,
   запускающую Yookassa_Payment_Flow.
5. WHEN Reservation в статусе `payment_authorized`, THE Mobile_App SHALL
   показывать кнопки «Перенести» (открывает Карточку товара с
   `reservationId`) и «Вернуть деньги» (открывает диалог подтверждения).
6. WHEN пользователь подтверждает «Вернуть деньги», THE Mobile_App SHALL
   вызывать `POST /reservations/{id}/cancel` и обновлять статус брони
   локально без перезагрузки экрана.
7. WHEN Rental в статусе `active` или `overdue`, THE Mobile_App SHALL
   показывать кнопку «Вернуть», вызывающую `POST /me/rentals/{id}/return-request`
   и переводящую карточку в статус `return_in_progress`.
8. IF `POST /me/rentals/{id}/return-request` возвращает ошибку с кодом
   `LOCKER_OFFLINE`, `RETURN_CELL_NOT_AVAILABLE`,
   `RETURN_LOCKER_DIFFERENT_CITY`, `INVALID_RENTAL_STATUS`,
   `LOCKER_OPEN_NOT_CONFIRMED` или `ESI_OPEN_FAILED`, THEN THE Mobile_App
   SHALL показать тот же русский текст ошибки, что Web_App
   (`handleReturnRental`), и оставить кнопку «Выбрать другой постамат».
9. WHEN пользователь нажимает на карточку Rental или Reservation, THE
   Mobile_App SHALL открывать экран деталей заказа с полным составом
   полей, что и `/profile/orders/{id}` Web_App.
10. WHILE у пользователя нет ни одного Reservation и ни одного Rental,
    THE Mobile_App SHALL показывать EmptyState «Заказов пока нет» с тем
    же текстом, что и Web_App, независимо от состояния загрузки списков.

### Requirement 10: Профиль и редактирование

**User Story:** Как пользователь, я хочу видеть и редактировать свои данные
в мобильном приложении.

#### Acceptance Criteria

1. THE Mobile_App SHALL загружать профиль через `GET /me` и показывать
   телефон, имя, фамилию, отчество, e-mail, дату рождения и предпочтительный
   City.
2. WHEN пользователь меняет имя, фамилию, отчество или e-mail и нажимает
   «Сохранить», THE Mobile_App SHALL вызывать `PATCH /me` и показывать
   уведомление по тем же правилам `getProfileCompletion` и
   `buildProfileNotice`, что и Web_App.
3. THE Mobile_App SHALL показывать на экране Профиля карточку
   «Верификация» со статус-пилюлей (`Verification_Status`) и текстом
   причины (`rejectReason` или дефолтный текст для `approved`/`pending`).
4. WHEN пользователь нажимает «Открыть проверку», THE Mobile_App SHALL
   открывать экран Верификации (Requirement 11).
5. WHEN пользователь нажимает «Мои заказы», THE Mobile_App SHALL
   переключать вкладку bottom-nav на «Мои заказы».
6. WHEN пользователь нажимает «Выйти», THE Mobile_App SHALL применить
   правила выхода из Requirement 3.10.

### Requirement 11: Верификация документов

**User Story:** Как пользователь, я хочу подать документы на проверку
прямо из мобильного приложения, чтобы получить доступ к бронированию.

#### Acceptance Criteria

1. THE Mobile_App SHALL загружать текущее состояние проверки через
   `GET /me/verification` и показывать поля, которые требуют заполнения
   (`documentType`, `documentNumber`, `documentName`,
   `documentIssueDate`, `documentExpiryDate`).
2. WHEN пользователь выбирает «Сделать фото», THE Mobile_App SHALL
   запросить через `expo-image-picker` разрешения камеры или галереи и
   получить изображение документа в формате JPEG или PNG.
3. WHEN изображение получено, THE Mobile_App SHALL показывать превью с
   возможностью переснять или удалить до отправки.
4. WHEN пользователь нажимает «Отправить на проверку», THE Mobile_App
   SHALL отправить `POST /me/verification` с полями документа и
   приложенным файлом через `multipart/form-data`.
5. IF сервер возвращает ошибку валидации документа, THEN THE Mobile_App
   SHALL показать русский текст ошибки рядом с соответствующим полем.
6. WHEN Verification_Status переходит в `pending`, THE Mobile_App SHALL
   блокировать повторную отправку до получения решения и показывать
   статус «На проверке».
7. WHEN Verification_Status переходит в `rejected`, THE Mobile_App SHALL
   показывать `rejectReason` и разрешать отправить документы повторно.

### Requirement 12: Источник статичного контента (FAQ, Идеи, О сервисе, Условия)

**User Story:** Как пользователь, я хочу видеть в мобильном приложении те
же ответы и описания, что и на сайте.

#### Acceptance Criteria

1. THE Mobile_App SHALL получать список «Идей» через тот же эндпоинт,
   что и Web_App (`GET /rental-ideas`), и показывать их в виде сетки
   `IdeasClient`.
2. THE Mobile_App SHALL получать список FAQ из того же источника, что и
   `FAQClient` Web_App, и показывать в виде аккордеона с теми же
   вопросами и ответами.
3. THE Mobile_App SHALL показывать страницы «О сервисе» и
   «Условия аренды» с тем же текстовым содержимым, что и Web_App
   (`/about` и `/terms-rental`), и пересобирать страницы при обновлении
   текстов в общем источнике.
4. WHERE статичный контент Web_App ссылается на изображения, видео или
   внешние ресурсы, THE Mobile_App SHALL использовать те же URL,
   разрешённые `resolvePublicAssetUrl`, без локальных дубликатов.
5. THE Mobile_App SHALL открывать страницы «FAQ», «Идеи», «О сервисе»,
   «Условия аренды» из меню Профиля (раздел «Помощь и информация»).

### Requirement 13: Deep linking и universal links

**User Story:** Как пользователь, я хочу открывать ссылки на товары, брони
и возврат с оплаты из браузера, push-уведомлений и SMS прямо в приложении.

#### Acceptance Criteria

1. THE Mobile_App SHALL регистрировать схему `naprokatberu://` для iOS и
   Android.
2. THE Mobile_App SHALL обрабатывать universal links вида
   `https://naprokatberu.ru/products/{id}`,
   `https://naprokatberu.ru/profile/orders/{id}`,
   `https://naprokatberu.ru/payment/return`.
3. WHEN Mobile_App получает Deep_Link на товар, THE Mobile_App SHALL
   открывать экран Карточки товара с переданным `id` или `slug`.
4. WHEN Mobile_App получает Deep_Link на заказ, THE Mobile_App SHALL
   открывать экран деталей заказа с переданным `id`.
5. WHEN Mobile_App получает Deep_Link `naprokatberu://payment/return`
   или `https://naprokatberu.ru/payment/return`, THE Mobile_App SHALL
   применить правила Requirement 7.5.
6. IF Deep_Link не соответствует ни одному поддерживаемому шаблону, THEN
   THE Mobile_App SHALL открыть Главную и показать тост «Ссылка
   устарела или некорректна».

### Requirement 14: Push-уведомления

**User Story:** Как пользователь, я хочу получать уведомления о ключевых
событиях аренды, чтобы не пропустить дедлайн или статус.

#### Acceptance Criteria

1. THE Mobile_App SHALL запрашивать у пользователя разрешение на
   уведомления через Expo Notifications при первом успешном входе.
2. WHEN пользователь даёт разрешение, THE Mobile_App SHALL получать
   `expoPushToken` и регистрировать его на Backend_API через
   `POST /me/push-tokens` с полями `token`, `platform`, `appVersion`.
3. WHEN Backend_API публикует событие `reservation.payment_authorized`,
   `reservation.expiring_soon`, `rental.pickup_ready`,
   `rental.expiring_soon`, `rental.overdue` или
   `verification.decision`, THE Mobile_App SHALL принимать связанный
   Push_Notification и открывать соответствующий экран при тапе по
   уведомлению.
4. WHEN пользователь выходит из аккаунта, THE Mobile_App SHALL
   отправлять `DELETE /me/push-tokens/{token}` с `accessToken` до
   очистки локальной сессии.
5. IF пользователь отказался от уведомлений или система их отключила,
   THEN THE Mobile_App SHALL не пытаться повторно запросить разрешение
   автоматически и показывать в Профиле ссылку на системные настройки.
6. THE Mobile_App SHALL показывать пуши на iOS только в формате
   `alert + sound`, без `badge`, чтобы не конфликтовать с бейджем
   нижней навигации (Requirement 2.3).

### Requirement 15: Соответствие типов мобильного клиента типам бекенда

**User Story:** Как разработчик, я хочу, чтобы типы и поля API в мобайле
совпадали с тем, что использует веб, чтобы поведение не расходилось.

#### Acceptance Criteria

1. THE Mobile_App SHALL описывать `City`, `Locker`, `Product`,
   `ProductDetail`, `PricePlan`, `PricingQuote`, `Reservation`,
   `Rental`, `RentalListItem`, `UpcomingReservation`, `AppUser`,
   `VerificationState` с теми же полями и типами, что
   `web/src/shared/api/types.ts`.
2. WHEN Backend_API добавляет в ответ новое поле, THE Mobile_App SHALL
   считать его необязательным до тех пор, пока соответствующее поле не
   стало обязательным в Web_App.
3. WHEN значения статусов Reservation или Rental используются для
   ветвлений UI, THE Mobile_App SHALL применять те же литералы
   статусов, что и Web_App (`created`, `awaiting_payment`,
   `payment_authorized`, `cancelled`, `expired`, `confirmed`,
   `pickup_ready`, `pickup_opened`, `active`, `overdue`,
   `return_in_progress`, `completed`).
4. WHEN значения `Verification_Status` используются для ветвлений UI,
   THE Mobile_App SHALL применять те же литералы, что и Web_App
   (`none`, `pending`, `approved`, `rejected`).
5. THE Mobile_App SHALL форматировать денежные суммы через ту же
   функцию `formatMoney`, что и Web_App, и числовые подписи через
   `formatCountRu` / `pluralizeRu`.

### Requirement 16: Обработка сетевых ошибок и offline

**User Story:** Как пользователь, я хочу понимать, что произошло, если
интернет пропал или сервер не отвечает.

#### Acceptance Criteria

1. IF любой запрос к Backend_API завершается сетевой ошибкой, THEN THE
   Mobile_App SHALL показать плашку `alert-danger` с текстом «Не удалось
   связаться с сервером. Проверьте интернет и попробуйте ещё раз.» и
   кнопку «Повторить».
2. WHEN пользователь нажимает «Повторить», THE Mobile_App SHALL
   повторить последний запрос с теми же параметрами.
3. WHILE сетевые запросы выполняются, THE Mobile_App SHALL показывать
   индикатор загрузки на текущем экране (skeleton или ActivityIndicator)
   и блокировать повторное нажатие на основную кнопку действия.
4. IF Backend_API возвращает HTTP 5xx, THEN THE Mobile_App SHALL
   показать сообщение «Сервис временно недоступен. Попробуйте позже.» и
   позволить вернуться на предыдущий экран.
5. IF Backend_API возвращает HTTP 401 не из ситуации Requirement 3.8 —
   3.9, THEN THE Mobile_App SHALL очистить токены и открыть экран входа.

### Requirement 17: Безопасное хранение токенов и чувствительных данных

**User Story:** Как пользователь, я не хочу, чтобы токен моей сессии был
доступен другим приложениям.

#### Acceptance Criteria

1. THE Mobile_App SHALL хранить `accessToken`, `refreshToken` и
   `expoPushToken` в `expo-secure-store` (iOS Keychain, Android
   Keystore) и не хранить их в `AsyncStorage` или `SharedPreferences`.
2. THE Mobile_App SHALL не логировать значения токенов или кодов
   подтверждения в консоль и не отправлять их в любые сторонние
   аналитические сервисы.
3. WHEN пользователь выходит из аккаунта или Backend_API возвращает
   401 после неудачного refresh, THE Mobile_App SHALL удалить все
   значения токенов из `expo-secure-store`.
4. WHEN Mobile_App переходит в фон на iOS, THE Mobile_App SHALL
   скрывать содержимое экрана через `expo-screen-capture` или
   аналогичный механизм при наличии активной сессии.

### Requirement 18: Минимальные версии платформ и совместимость

**User Story:** Как разработчик, я хочу зафиксировать целевые версии
iOS и Android, чтобы не вырабатывать поддержку устаревших устройств.

#### Acceptance Criteria

1. THE Mobile_App SHALL поддерживать iOS 15.1 и выше.
2. THE Mobile_App SHALL поддерживать Android 8.0 (API 26) и выше.
3. THE Mobile_App SHALL использовать Expo SDK 55 (тот, что в
   `mobile/package.json`) и React Native 0.83.x.
4. THE Mobile_App SHALL запускаться на портретной ориентации; при
   повороте устройства интерфейс SHALL оставаться в портретной
   ориентации, кроме экрана галереи фотографий товара.
5. THE Mobile_App SHALL занимать не больше 60 МБ установленного
   размера на Android (release APK / AAB) после оптимизации иконок и
   шрифтов.
