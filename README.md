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

## Production file uploads

The backend already supports direct presigned uploads to S3-compatible storage.

Use `backend/.env.production.example` as the base and configure:

```bash
UPLOAD_DEV_STUB=false
STORAGE_PROVIDER=s3
S3_ENDPOINT_URL=https://your-s3-endpoint
S3_FORCE_PATH_STYLE=true   # enable for many S3-compatible providers
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
S3_PUBLIC_BUCKET=naprokatberu-public
S3_PRIVATE_BUCKET=naprokatberu-private
MEDIA_PUBLIC_BASE_URL=https://cdn.naprokatberu.ru
```

Notes:

- `S3_PUBLIC_BUCKET` is for product photos that are shown on the site.
- `S3_PRIVATE_BUCKET` is for verification documents and other non-public files.
- `MEDIA_PUBLIC_BASE_URL` must point only to the public media surface, for example a CDN or a bucket/domain that serves product images.
- The storage bucket must allow browser `PUT` requests from your web domain for the presigned upload flow to work.
