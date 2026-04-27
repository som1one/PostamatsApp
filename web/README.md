# Postamats Web

Client web app for the Postamats FastAPI backend.

## Environment

Create `web/.env.local` when running locally:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_YANDEX_MAPS_API_KEY=
```

Backend payment return should point to the web app:

```bash
WEB_APP_ORIGIN=http://localhost:3000
YOOKASSA_RETURN_URL=http://localhost:3000/payment/return
```

If the Yandex key is empty, `/lockers` shows the fallback list.
