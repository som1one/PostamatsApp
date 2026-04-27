# PostamatsApp

## Web client

The customer web app lives in `web/`.

Local environment:

```bash
cd web
npm install
npm run dev
```

Recommended env:

```bash
# web/.env.local
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_YANDEX_MAPS_API_KEY=

# backend/.env or root .env.local
WEB_APP_ORIGIN=http://localhost:3000
YOOKASSA_RETURN_URL=http://localhost:3000/payment/return
```

If the Yandex key is empty, the site keeps the postamat list fallback.
