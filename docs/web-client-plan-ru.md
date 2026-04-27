# Web client MVP

`web/` is the customer-facing Next.js client for the existing FastAPI backend.

## Implemented surface

- Public catalog and product detail.
- Public lockers page with Yandex Maps when `NEXT_PUBLIC_YANDEX_MAPS_API_KEY` is set.
- Phone auth through `/auth/request-code` and `/auth/confirm-code`.
- Bearer token storage with refresh support.
- Profile, KYC form, presign upload, and `/me/verification`.
- Checkout quote, reservation create, payment preauth, and `/payment/return`.
- Rentals list and return request.

## Environment

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_YANDEX_MAPS_API_KEY=
WEB_APP_ORIGIN=http://localhost:3000
YOOKASSA_RETURN_URL=http://localhost:3000/payment/return
```

## Known first-iteration limitations

- Payment confirmation depends on YooKassa webhook changing payment status to `authorized`.
- In backend dev stub mode, the payment can stay `pending` unless a webhook/status update is simulated.
- The site uses the shared public API; no separate `/web` namespace is introduced.
