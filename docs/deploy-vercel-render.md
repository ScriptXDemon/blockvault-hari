# Hosted deployment: Vercel + Render

BlockVault is deployed as a split stack:

- Vercel hosts the React SPA
- Render hosts the FastAPI API and Celery worker
- MongoDB Atlas stores metadata
- AWS S3 stores encrypted objects and ZKPT runtime artifacts
- Render Key Value provides Redis for Celery

## 1. Push the repo

Create a deployment branch and push it to the target repository:

```bash
git checkout -b codex/deploy-vercel-render
git remote add scriptxdemon https://github.com/ScriptXDemon/blockvault-hari
git add .
git commit -m "Prepare Vercel and Render deployment"
git push scriptxdemon codex/deploy-vercel-render
```

## 2. Upload the runtime proof artifacts

The large `.zkey` files are intentionally not pushed to Git. Upload the active runtime artifacts from your local machine to S3 before booting Render:

```bash
python scripts/zkpt/upload_artifacts.py --bucket <artifact-bucket-name>
```

Default uploaded profiles:

- `v4_sparse`
- `v3a`

Default prefix:

- `zkpt-artifacts`

If you use a non-AWS S3-compatible endpoint, add:

```bash
python scripts/zkpt/upload_artifacts.py \
  --bucket <bucket> \
  --endpoint-url <endpoint> \
  --access-key-id <key> \
  --secret-access-key <secret> \
  --force-path-style
```

## 3. Create the Render services

Use the committed root-level `render.yaml` Blueprint.

The Blueprint creates:

- `blockvault-api` web service
- `blockvault-worker` worker service
- `blockvault-redis` key-value store

Fill these env vars in Render:

- `BLOCKVAULT_FRONTEND_ORIGINS=https://<your-vercel-domain>`
- `BLOCKVAULT_FRONTEND_ORIGIN_REGEX=` if you want preview-domain regex support
- `BLOCKVAULT_MONGO_URI=<mongodb-atlas-uri>`
- `BLOCKVAULT_STORAGE_S3_BUCKET=<object-storage-bucket>`
- `BLOCKVAULT_STORAGE_S3_ACCESS_KEY_ID=<aws-access-key>`
- `BLOCKVAULT_STORAGE_S3_SECRET_ACCESS_KEY=<aws-secret-key>`
- `BLOCKVAULT_SIWE_DOMAIN=<your-vercel-domain-without-https>`
- `BLOCKVAULT_SIWE_URI=https://<your-vercel-domain>`
- `BLOCKVAULT_ZKPT_ARTIFACTS_S3_BUCKET=<artifact-bucket-or-same-storage-bucket>`

The staged hosted config intentionally keeps:

- `BLOCKVAULT_APP_ENV=staging`
- `BLOCKVAULT_ENABLE_TEST_AUTH=true`

That preserves the software-testable hosted auto-login flow. Switch to `production` and disable test auth only when you are ready to harden the public deployment.

## 4. Create the Vercel project

Use the repo root as the Vercel project root. The committed `vercel.json` already tells Vercel to:

- install from the monorepo root
- build the frontend with `npm run build:web`
- publish `apps/web/dist`
- rewrite SPA routes to `index.html`

Set these Vercel env vars:

- `VITE_API_BASE_URL=https://<your-render-api-domain>`
- `VITE_AUTOMATION_BYPASS_AUTH=true`
- `VITE_AUTOMATION_WALLET_ADDRESS=0x1111111111111111111111111111111111111111`
- `VITE_AUTOMATION_DISPLAY_NAME=Automation Tester`

## 5. Smoke check after deploy

Render:

- `GET https://<render-api-domain>/health`
- `GET https://<render-api-domain>/status`

Vercel:

- open `/`
- refresh `/app/vault`
- confirm the build ID is visible in the sidebar footer

Functional checks:

- vault upload/download/delete
- case creation
- document upload
- direct-PDF redaction
- OCR-assisted scanned-PDF redaction
- verified ZKPT bundle generation
