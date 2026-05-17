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

Production uploads now use local filesystem storage inside the backend container, so the project can be deployed without S3 or MinIO.

Use `backend/.env.production.example` as the base and configure:

```bash
UPLOAD_DEV_STUB=false
STORAGE_PROVIDER=filesystem
LOCAL_UPLOAD_ROOT=/app/assets/runtime-uploads
```

Notes:

- Uploaded files are written under `backend_uploads` at `/app/assets/runtime-uploads` in the container.
- Public file URLs are served from the backend asset route and resolved by the web client automatically.
- If you later switch back to S3, the same presign flow still exists, but filesystem mode is the deploy-safe default.

## Catalog sync

Export the local catalog bundle before deploy:

```bash
python -m scripts.export_catalog_bundle --output deploy/catalog-sync.bundle.json
```

After the server is updated and containers are rebuilt, run a dry-run first and then apply the bundle inside the backend image:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml run --rm backend python -m scripts.apply_catalog_bundle --bundle /app/deploy/catalog-sync.bundle.json
docker compose --env-file deploy/.env -f deploy/docker-compose.beget.yml run --rm backend python -m scripts.apply_catalog_bundle --bundle /app/deploy/catalog-sync.bundle.json --apply
```

For IP-only deploy, replace `deploy/.env` and `deploy/docker-compose.beget.yml` with `deploy/.env.ip` and `deploy/docker-compose.ip.yml`.
Only add `--deactivate-missing-products` when you intentionally want to disable server-side products that are not present in the bundle.

## Deploy

Production compose files and command examples live in [deploy/README.md](/C:/Users/Green_Tea/Documents/New%20project/deploy/README.md).
