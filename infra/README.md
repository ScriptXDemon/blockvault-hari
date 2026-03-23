# Local infrastructure

The fresh BlockVault rebuild now ships a production-like local stack with:

- MongoDB
- Redis
- MinIO
- FastAPI served by Gunicorn
- Celery worker
- Vite frontend compiled and served by Nginx

Start them with:

```bash
docker compose -f infra/docker-compose.local.yml up -d
```

or from the repo root:

```bash
npm run stack:up
```

Default ports:

- MongoDB: `27017`
- Redis: `6379`
- MinIO API: `9000`
- MinIO console: `9001`
- API: `8000`
- Web: `4173`

The fresh API can now use MinIO through the S3-compatible storage backend:

```bash
$env:BLOCKVAULT_STORAGE_BACKEND="s3"
$env:BLOCKVAULT_STORAGE_S3_ENDPOINT_URL="http://127.0.0.1:9000"
$env:BLOCKVAULT_STORAGE_S3_BUCKET="blockvault-local"
$env:BLOCKVAULT_STORAGE_S3_ACCESS_KEY_ID="blockvault"
$env:BLOCKVAULT_STORAGE_S3_SECRET_ACCESS_KEY="blockvault123"
```

The bucket is auto-created by the API if it is missing and `BLOCKVAULT_STORAGE_S3_AUTO_CREATE_BUCKET=true`.

The compose file already injects those MinIO settings into the API and worker containers, so no extra host configuration is required for the local stack.

Useful companion commands:

```bash
npm run stack:ps
npm run stack:down
```
