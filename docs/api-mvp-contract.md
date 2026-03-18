# API Contract for Postamat Rental MVP

This document describes the backend endpoints needed for a 15-day pilot MVP.
The backend is assumed to be implemented separately. The goal here is to lock
the contract surface: what endpoint is needed, who calls it, and why it exists.

## MVP Scope

Pilot scope assumed for this contract:

- 1 city
- 10-15 SKUs
- daily rent first
- manual KYC approval in admin
- happy path for locker issue/return
- operator fallback for incidents

Out of scope for first release:

- full franchise permissions
- hourly pricing
- automatic overdue prolongation
- complex analytics
- full incident automation

## Core Rental Flow

Main user flow:

1. User signs in with phone and SMS code.
2. User uploads passport photos for verification.
3. Admin manually approves verification.
4. User selects city and locker on map.
5. User opens product card and sees availability and price.
6. User creates reservation for a SKU in a specific locker.
7. User passes preauthorization in YooKassa.
8. Backend reserves a cell in the postamat and creates a pickup PIN.
9. User enters PIN at the locker, cell opens, rent starts.
10. User returns item, backend opens return cell, close event finishes rental.

## Common Conventions

Base assumptions:

- Base path: `/api/v1`
- Auth: `Authorization: Bearer <token>`
- Time format: ISO 8601 UTC
- IDs: UUID strings
- Money: integer in kopecks
- Pagination: `page`, `limit`
- Client app versions should be accepted through headers:
  - `X-Platform: ios | android | admin`
  - `X-App-Version: semver`

Suggested common response envelope:

```json
{
  "data": {},
  "meta": {},
  "error": null
}
```

Suggested error envelope:

```json
{
  "data": null,
  "error": {
    "code": "LOCKER_OFFLINE",
    "message": "Locker is temporarily unavailable",
    "details": {}
  }
}
```

## Domain Entities

Minimum entities to support the MVP:

- `user`
- `verification`
- `city`
- `locker_location`
- `locker_cell`
- `product`
- `inventory_unit`
- `reservation`
- `payment`
- `rental`
- `rental_event`
- `support_incident`
- `admin_user`

Important distinction:

- `product` is SKU-level catalog data.
- `inventory_unit` is the physical rentable item in a locker cell.

## Endpoint Priority

Priority meaning:

- `P0`: required for pilot launch
- `P1`: should be added right after P0 if time allows
- `P2`: can wait until after pilot

## 1. Auth and Session

### `POST /auth/request-code`

- Consumer: mobile
- Priority: `P0`
- Why: start login with phone number

Request:

```json
{
  "phone": "+79991234567"
}
```

Response:

```json
{
  "data": {
    "verificationSessionId": "uuid",
    "ttlSeconds": 60
  }
}
```

### `POST /auth/confirm-code`

- Consumer: mobile
- Priority: `P0`
- Why: exchange SMS code for app tokens

Request:

```json
{
  "verificationSessionId": "uuid",
  "code": "1234"
}
```

Response:

```json
{
  "data": {
    "accessToken": "jwt",
    "refreshToken": "jwt",
    "user": {
      "id": "uuid",
      "phone": "+79991234567",
      "verificationStatus": "not_started"
    }
  }
}
```

### `POST /auth/refresh`

- Consumer: mobile, admin
- Priority: `P0`
- Why: renew expired access token

### `POST /auth/logout`

- Consumer: mobile, admin
- Priority: `P1`
- Why: invalidate session on device

## 2. User and Verification

### `GET /me`

- Consumer: mobile
- Priority: `P0`
- Why: get current profile and gating status

Must return:

- `verificationStatus`
- `activeRentalCount`
- `defaultCityId`
- `hasSavedCard`

### `PATCH /me`

- Consumer: mobile
- Priority: `P1`
- Why: update name, email, preferred city

### `POST /me/verification`

- Consumer: mobile
- Priority: `P0`
- Why: create or update verification request

Suggested payload:

```json
{
  "firstName": "Ivan",
  "lastName": "Ivanov",
  "birthDate": "1995-08-20",
  "documentType": "passport_rf",
  "documentNumber": "1234567890",
  "files": [
    {
      "fileKey": "s3-key-front",
      "kind": "document_front"
    },
    {
      "fileKey": "s3-key-selfie",
      "kind": "selfie"
    }
  ]
}
```

### `GET /me/verification`

- Consumer: mobile
- Priority: `P0`
- Why: show current verification status and rejection reason

Statuses:

- `not_started`
- `pending_review`
- `approved`
- `rejected`
- `blocked`

### `POST /uploads/presign`

- Consumer: mobile, admin
- Priority: `P0`
- Why: upload passport photos or product issue photos directly to storage

## 3. Cities and Lockers

### `GET /cities`

- Consumer: mobile
- Priority: `P0`
- Why: city picker for pilot and future scale

### `GET /lockers`

- Consumer: mobile, admin
- Priority: `P0`
- Why: return locker locations for map and admin list

Recommended filters:

- `cityId`
- `status=online|offline|maintenance`
- `hasAvailableItems=true`

Each locker should return:

- address
- geo coordinates
- working hours
- online status
- available product count

### `GET /lockers/:lockerId`

- Consumer: mobile, admin
- Priority: `P0`
- Why: details page for pickup point

Must return:

- public info for customers
- locker operational state
- list of available products or count summary

### `GET /lockers/:lockerId/availability`

- Consumer: mobile
- Priority: `P0`
- Why: quick availability check before reservation

Response should answer:

- which SKUs are available right now
- minimum rent period
- next unavailable time if known

## 4. Catalog

### `GET /categories`

- Consumer: mobile, admin
- Priority: `P1`
- Why: category tabs and filters

### `GET /products`

- Consumer: mobile, admin
- Priority: `P0`
- Why: catalog list screen

Recommended filters:

- `cityId`
- `lockerId`
- `categoryId`
- `search`
- `availableOnly=true`

Each product in list should include:

- id
- name
- cover image
- short specs
- price from
- availability flag

### `GET /products/:productId`

- Consumer: mobile, admin
- Priority: `P0`
- Why: product detail screen

Must return:

- description
- characteristics
- rental rules
- included accessories
- available lockers
- price options

### `GET /products/:productId/pricing`

- Consumer: mobile
- Priority: `P0`
- Why: separate price calculation source for checkout

Query params:

- `lockerId`
- `durationType=day`
- `durationValue=1`

Response:

```json
{
  "data": {
    "currency": "RUB",
    "baseAmount": 150000,
    "discountAmount": 0,
    "totalAmount": 150000,
    "depositAmount": 0,
    "preauthAmount": 150000
  }
}
```

## 5. Reservations

### `POST /reservations/quote`

- Consumer: mobile
- Priority: `P0`
- Why: lock checkout math before reservation creation

This endpoint should validate:

- user is verified
- product exists
- locker is online
- inventory is available
- tariff is valid

### `POST /reservations`

- Consumer: mobile
- Priority: `P0`
- Why: create reservation before payment

Suggested payload:

```json
{
  "productId": "uuid",
  "lockerId": "uuid",
  "durationType": "day",
  "durationValue": 1,
  "pickupWindowMinutes": 120
}
```

Must create:

- reservation record
- expiration timestamp
- frozen quote snapshot

### `GET /reservations/:reservationId`

- Consumer: mobile
- Priority: `P0`
- Why: show reservation summary and countdown

### `POST /reservations/:reservationId/cancel`

- Consumer: mobile, admin
- Priority: `P1`
- Why: release inventory and payment hold if booking is cancelled

## 6. Payments

### `POST /payments/preauth`

- Consumer: mobile
- Priority: `P0`
- Why: initialize YooKassa preauthorization for reservation

Input:

- `reservationId`
- `paymentMethodId` or payment token

Output should include:

- payment status
- confirmation URL or SDK params
- whether saved card exists

### `POST /payments/webhooks/yookassa`

- Consumer: YooKassa
- Priority: `P0`
- Why: backend must react to async payment state changes

Must handle:

- waiting for capture
- succeeded
- canceled
- failed

### `GET /payments/:paymentId`

- Consumer: mobile, admin
- Priority: `P1`
- Why: show current payment state and debug issues

### `GET /me/payment-methods`

- Consumer: mobile
- Priority: `P1`
- Why: display saved cards for repeat rent

## 7. Rental Start and Pickup

### `POST /reservations/:reservationId/confirm`

- Consumer: mobile
- Priority: `P0`
- Why: finalize reservation after successful preauth

What backend should do here:

1. confirm payment is valid
2. select physical inventory unit
3. reserve locker cell through ESI API
4. generate pickup PIN
5. create rental in `pickup_ready`

Response should include:

- `rentalId`
- `pickupPin`
- `lockerId`
- `expiresAt`

### `GET /rentals/active`

- Consumer: mobile
- Priority: `P0`
- Why: app home should know if user has active or pending rent

### `GET /rentals/:rentalId`

- Consumer: mobile, admin
- Priority: `P0`
- Why: full rental timeline and current state

Must return:

- product info
- locker info
- pickup PIN if still relevant
- start/end time
- payment summary
- current status

### `POST /rentals/:rentalId/start`

- Consumer: system or admin tool, not mobile button
- Priority: `P0`
- Why: explicit start transition after locker open event

Recommended trigger:

- ESI webhook says pickup cell was opened

Do not rely on the mobile app to declare rent started.

## 8. Return Flow

### `POST /rentals/:rentalId/return-request`

- Consumer: mobile
- Priority: `P0`
- Why: user initiates return and backend opens proper cell

Backend should:

1. validate rental is returnable
2. find return locker and free cell
3. call ESI open command
4. mark rental as `return_in_progress`

### `POST /rentals/:rentalId/return-complete`

- Consumer: system or admin tool
- Priority: `P0`
- Why: finalize rental after close webhook

Recommended trigger:

- ESI webhook says target return cell was closed

Backend should:

1. capture payment if needed
2. close rental
3. free inventory/cell state

### `POST /rentals/:rentalId/extend`

- Consumer: mobile
- Priority: `P1`
- Why: manual prolongation from app

Can be delayed if pilot launch is very tight.

## 9. Postamat Integration

These are not public mobile endpoints, but backend integration boundaries.

### `POST /integrations/esi/lockers/:lockerExternalId/reserve`

- Consumer: internal backend module only
- Priority: `P0`
- Why: abstract third-party reservation details from business domain

### `POST /integrations/esi/lockers/:lockerExternalId/open`

- Consumer: internal backend module only
- Priority: `P0`
- Why: open pickup or return cell

### `POST /webhooks/esi`

- Consumer: ESI API
- Priority: `P0`
- Why: receive locker state changes

Must handle events:

- cell open
- cell close
- offline
- online
- occupied
- vacant
- unexpected open
- device error

Must map external events to:

- locker status updates
- rental transitions
- alerts for operator

## 10. Incidents and Support

### `POST /support/incidents`

- Consumer: mobile, admin
- Priority: `P1`
- Why: report damaged item, locker issue, missing accessory

Suggested payload:

```json
{
  "rentalId": "uuid",
  "type": "locker_open_failed",
  "description": "User entered PIN but the cell did not open",
  "attachments": ["s3-key-1"]
}
```

### `GET /support/incidents/:incidentId`

- Consumer: mobile, admin
- Priority: `P2`
- Why: allow issue status tracking later

For pilot, this may be handled only in admin.

## 11. Push Notifications

### `POST /me/push-tokens`

- Consumer: mobile
- Priority: `P1`
- Why: register Firebase token for notifications

### `DELETE /me/push-tokens/:tokenId`

- Consumer: mobile
- Priority: `P2`
- Why: cleanup old devices

Push events worth supporting early:

- reservation created
- payment success/failure
- pickup reminder
- rental ending soon
- return confirmation

## 12. Rental History

### `GET /me/rentals`

- Consumer: mobile
- Priority: `P0`
- Why: history and active rentals list

Recommended filters:

- `status=active|completed|cancelled`
- `page`
- `limit`

### `GET /me/rentals/:rentalId`

- Consumer: mobile
- Priority: `P0`
- Why: detail page in history

## 13. Admin Auth

### `POST /admin/auth/login`

- Consumer: admin
- Priority: `P0`
- Why: admin panel sign in

### `POST /admin/auth/refresh`

- Consumer: admin
- Priority: `P0`
- Why: keep admin session alive

## 14. Admin Users and Verification

### `GET /admin/users`

- Consumer: admin
- Priority: `P0`
- Why: user search and moderation

Filters:

- phone
- verification status
- blocked state

### `GET /admin/users/:userId`

- Consumer: admin
- Priority: `P0`
- Why: user profile, rentals, payments

### `POST /admin/users/:userId/approve-verification`

- Consumer: admin
- Priority: `P0`
- Why: manual KYC approval for MVP

### `POST /admin/users/:userId/reject-verification`

- Consumer: admin
- Priority: `P0`
- Why: reject KYC with a clear reason

### `POST /admin/users/:userId/block`

- Consumer: admin
- Priority: `P1`
- Why: prevent abusive or risky users from renting

## 15. Admin Lockers

### `GET /admin/lockers`

- Consumer: admin
- Priority: `P0`
- Why: locker monitoring table

### `GET /admin/lockers/:lockerId`

- Consumer: admin
- Priority: `P0`
- Why: detailed locker state, cells, recent events

### `POST /admin/lockers`

- Consumer: admin
- Priority: `P1`
- Why: add locker records without DB access

### `PATCH /admin/lockers/:lockerId`

- Consumer: admin
- Priority: `P1`
- Why: update address, city, status, working hours

### `POST /admin/lockers/:lockerId/open-cell`

- Consumer: admin
- Priority: `P1`
- Why: operator emergency action when pickup/return fails

## 16. Admin Products and Inventory

### `GET /admin/products`

- Consumer: admin
- Priority: `P0`
- Why: SKU list and availability control

### `POST /admin/products`

- Consumer: admin
- Priority: `P1`
- Why: create new SKU

### `PATCH /admin/products/:productId`

- Consumer: admin
- Priority: `P1`
- Why: update card data and rental rules

### `GET /admin/inventory-units`

- Consumer: admin
- Priority: `P0`
- Why: track physical items by locker and status

Statuses:

- `available`
- `reserved`
- `rented`
- `damaged`
- `maintenance`
- `lost`

### `PATCH /admin/inventory-units/:unitId`

- Consumer: admin
- Priority: `P1`
- Why: move unit, mark damaged, assign locker cell

## 17. Admin Rentals and Operations

### `GET /admin/rentals`

- Consumer: admin
- Priority: `P0`
- Why: operations dashboard for current rentals

Useful filters:

- city
- locker
- status
- overdue

### `GET /admin/rentals/:rentalId`

- Consumer: admin
- Priority: `P0`
- Why: inspect event timeline and payment state

### `POST /admin/rentals/:rentalId/cancel`

- Consumer: admin
- Priority: `P1`
- Why: operator rescue for stuck reservations

### `POST /admin/rentals/:rentalId/force-complete`

- Consumer: admin
- Priority: `P1`
- Why: recover from missing webhook or manual reconciliation

## 18. Recommended Status Models

### Verification Status

- `not_started`
- `pending_review`
- `approved`
- `rejected`
- `blocked`

### Reservation Status

- `created`
- `awaiting_payment`
- `payment_authorized`
- `confirmed`
- `expired`
- `cancelled`

### Rental Status

- `pickup_ready`
- `pickup_opened`
- `active`
- `return_in_progress`
- `completed`
- `overdue`
- `cancelled`
- `incident`

### Locker Status

- `online`
- `offline`
- `maintenance`
- `degraded`

## 19. Launch Order

Implement in this order to reduce risk.

### Wave 1

- auth
- me
- verification
- cities
- lockers
- products
- pricing

### Wave 2

- reservation quote
- reservation create
- payment preauth
- reservation confirm
- active rental

### Wave 3

- ESI webhook handling
- rental start
- return request
- return complete
- rental history

### Wave 4

- admin user review
- admin locker monitoring
- admin rental monitoring
- emergency operator actions

### Wave 5

- support incidents
- push tokens
- extend rental

## 20. What Can Be Faked Temporarily

If time is collapsing, these can be simplified for pilot:

- KYC: manual approval in admin
- notifications: cron + simple push/email
- issue workflow: save incident and notify operator
- analytics: SQL queries in admin instead of dashboards
- saved cards: optional if YooKassa integration timeline slips

## 21. What Must Not Be Faked

These parts should be real before pilot:

- auth and token security
- reservation expiration
- payment state tracking
- locker open/close event processing
- inventory-unit to cell linkage
- admin visibility into stuck rentals

## 22. Minimal Questions to Freeze Before Coding

These business rules should be answered before implementation:

1. Can user create reservation before verification approval?
2. Is return allowed only to the same locker or any locker?
3. When exactly is payment captured: on pickup, on return, or both?
4. What happens if preauth succeeded but locker reservation failed?
5. What is the timeout if user does not pick up reserved item?
6. What is the operator action if close webhook never arrives?
7. Can one locker hold multiple units of the same SKU?

## 23. Suggested Next Backend Artifact

The next useful file after this one would be:

- `openapi.yaml` for the `P0` endpoints only

Start with these sections first:

- auth
- me
- verification
- lockers
- products
- reservations
- payments
- rentals
- admin basic operations
