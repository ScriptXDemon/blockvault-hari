# BlockVault

BlockVault is a clean-slate rebuild of the original project as a wallet-first legal document platform with a separate encrypted private vault.

## Product boundary

The fresh v1 scope is intentionally narrow:

- wallet-first SIWE authentication with cookie-backed sessions
- encrypted private vault upload, list, download, delete, and sharing
- case-based legal document management
- document notarization and evidence export
- asynchronous redaction with an authoritative ZKPT integration boundary
- immutable chain-of-custody timeline

Explicitly excluded from the new codebase for v1:

- AI analysis
- BCDN workflows
- signature workflows
- experimental and auxiliary research modules

## Monorepo layout

- `apps/web`: Vite React client
- `apps/api`: FastAPI application
- `apps/worker`: Celery worker entrypoint
- `packages/ui`: shared design system primitives
- `packages/contracts`: shared TypeScript API contracts
- `infra`: local docker stack and deployment manifests
- `docs`: product spec, runbooks, and patent boundary

## Legacy archive

The pre-rebuild implementation has been moved out of the working tree and archived externally at:

- `D:\BlockVault-Legacy-Reference-20260312-025428`

That archive contains the historical patent notes, ZKPT reference material, old workflow tests, and the removed runtime implementation.

## Local development

### Web

```bash
npm install
npm run dev:web
```

### API

```bash
python -m pip install -e apps/api[dev]
npm run dev:api
```

### Worker

```bash
python -m pip install -e apps/worker
npm run dev:worker
```

### Local infrastructure

```bash
docker compose -f infra/docker-compose.local.yml up -d
```

or:

```bash
npm run stack:up
```

That compose stack now includes:

- MongoDB
- Redis
- MinIO
- FastAPI behind Gunicorn on `http://127.0.0.1:8000`
- Celery worker
- production-built web UI on `http://127.0.0.1:4173`

To use the local MinIO service instead of the fallback filesystem store:

```bash
$env:BLOCKVAULT_STORAGE_BACKEND="s3"
$env:BLOCKVAULT_STORAGE_S3_ENDPOINT_URL="http://127.0.0.1:9000"
$env:BLOCKVAULT_STORAGE_S3_BUCKET="blockvault-local"
$env:BLOCKVAULT_STORAGE_S3_ACCESS_KEY_ID="blockvault"
$env:BLOCKVAULT_STORAGE_S3_SECRET_ACCESS_KEY="blockvault123"
```

In `BLOCKVAULT_APP_ENV=production`, the API now refuses to boot unless the object-store backend is `s3` and the configured bucket is reachable.

For a production-like local run, prefer the compose stack over `uvicorn --reload` and `vite dev`.

Useful stack commands:

```bash
npm run stack:ps
npm run stack:down
```

## Hosted deployment

The hosted split deployment uses:

- Vercel for the frontend SPA
- Render for the API and worker
- MongoDB Atlas for metadata
- AWS S3 for encrypted objects and ZKPT runtime artifacts

The repo now includes:

- [vercel.json](./vercel.json)
- [render.yaml](./render.yaml)
- [docs/deploy-vercel-render.md](./docs/deploy-vercel-render.md)

One important constraint: the large ZKPT `.zkey` files are not meant to be pushed to GitHub. Upload them to S3 from your local machine before booting the hosted backend:

```bash
npm run zkpt:artifacts:upload -- --bucket <artifact-bucket-name>
```

### Local browser workflow check

The fresh rebuild includes a repeatable local browser runner for the core `Vault -> Cases -> Documents -> Evidence` flow.

Start the web and API locally with test auth enabled:

```bash
$env:BLOCKVAULT_ENABLE_TEST_AUTH="true"
npm run dev:web
python -m uvicorn blockvault_api.main:app --app-dir apps/api/src --host 127.0.0.1 --port 8000
```

Then run:

```bash
npm run e2e:local
```

Artifacts and screenshots are written to `output/playwright/`.
### Authoritative ZKPT runtime

The repo now carries three authoritative PLONK profiles:

- `v4_sparse`: the default sparse-update production profile
- `v3a`: the preserved fast full-window baseline
- `v2`: the heavier baseline profile retained for reproducibility and comparison

The fresh rebuild uses a split PLONK path, `snarkjs wtns calculate` plus `snarkjs plonk prove`, instead of `snarkjs fullprove`.

Current measured results on this machine:

- `v2`: about `282-296s` total prove time with a `1.985 GiB` zkey
- `v3a`: about `77-89s` total prove time for single-shard full-window proofs
- `v4_sparse`: about `80-91s` total prove time for single-proof sparse-update flows, while keeping larger documents on a single proof when only a few canonical segments change

`v4_sparse` is now the default selected profile because it keeps the same `canonical_segment_mask_v1` proof boundary while making proof count scale with modified segments instead of total document windows.

The default proof budget remains `360` seconds so larger multi-shard documents still have room to complete, but the default profile is no longer the heavy baseline.

You can select an artifact profile independently from the artifact root:

```bash
$env:BLOCKVAULT_ZKPT_PROFILE="v4_sparse"
```

By default that resolves to `circuits/zkpt/<profile>`. If you keep the default artifact directory, switching `BLOCKVAULT_ZKPT_PROFILE` is enough to move between the sparse default profile, the preserved full-window baseline, and the heavier reproducibility baseline.

You can override the proof budget explicitly when needed:

```bash
$env:BLOCKVAULT_ZKPT_PROOF_TIMEOUT_SECONDS="360"
```

`/health` and `/status` surface the selected profile, discovered profiles, active prover backend, helper/runtime readiness, and warnings when the current artifact profile is likely to outrun the configured budget.

The runtime now also exposes:

- `zkpt_runtime.recentSingleProofBenchmark`
- `zkpt_runtime.preflightThresholds`
- `zkpt_runtime.onchain`

Redaction jobs classify themselves before proving:

- `single_proof_ready`
- `verified_bundle_only`
- `unsupported_until_v4`

The classification is returned on the redaction job, the persisted ZKPT bundle, and the document result payload. Single-proof bundles that stay inside the direct verifier budget are marked `onchain_eligible=true`; multi-shard bundles remain exportable and verified off-chain but are not treated as first-release on-chain candidates.

The API also enforces artifact compatibility before any bundle can be marked verified:

The runtime now also distinguishes proof models explicitly:

- `full_segment_windows`: preserved authoritative profiles (`v2`, `v3a`, `v3b`, `v3c`)
- `sparse_update`: active `v4_sparse` profile for modified-segment proving


- the selected profile must declare `profile_class: "authoritative"`
- the selected profile must declare `proof_boundary: "canonical_segment_mask_v1"`

If either check fails, redaction proving stays fail-closed and no verified bundle is emitted.

In `BLOCKVAULT_APP_ENV=production`, startup is stricter:

- `BLOCKVAULT_DEBUG` must be `false`
- `BLOCKVAULT_ENABLE_TEST_AUTH` must be `false`
- `BLOCKVAULT_SECRET_KEY` must not be left at the default value
- configured frontend origins must not point at `localhost` or `127.0.0.1`
- `BLOCKVAULT_SIWE_DOMAIN` and `BLOCKVAULT_SIWE_URI` must not use localhost values
- the ZKPT runtime must be authoritative-ready
- the redaction runtime must be ready

If either condition fails, the API refuses to boot instead of serving degraded production semantics.

### Request rate limits

The fresh API now applies a basic in-memory rate limit to the highest-risk write surfaces:

- `POST /api/auth/siwe/nonce`
- `POST /api/auth/siwe/verify`
- `POST /api/auth/test-login`
- `POST /api/v1/files/init-upload`
- `POST /api/v1/redactions/jobs`

Config knobs:

```bash
BLOCKVAULT_RATE_LIMIT_AUTH_REQUESTS=20
BLOCKVAULT_RATE_LIMIT_AUTH_WINDOW_SECONDS=60
BLOCKVAULT_RATE_LIMIT_WRITE_REQUESTS=10
BLOCKVAULT_RATE_LIMIT_WRITE_WINDOW_SECONDS=60
```

This limiter is intentionally small and process-local. It is suitable for local use and single-instance staging, but production deployment should replace it with a distributed limit at the edge or API gateway.

### Upload size limits

The API now enforces a hard payload ceiling on encrypted vault and legal document uploads at both the declared init step and the actual multipart upload step.

Config knob:

```bash
BLOCKVAULT_MAX_UPLOAD_BYTES=26214400
```

The default is `25 MiB`. Requests over the limit return `413`.

### ZKPT runtime probe

The rebuild now includes a live runtime probe for the authoritative witness and prover path. It uses the same projection, witness generation, and prove/verify code as the redaction workflow, but against a deterministic built-in text fixture unless you override it.

Run it with:

```bash
npm run zkpt:probe
```

Useful variants:

```bash
python scripts/zkpt/runtime_probe.py --stdout-only
python scripts/zkpt/runtime_probe.py --term privileged --term confidential
python scripts/zkpt/runtime_probe.py --text "Confidential memo for BlockVault." --output output/zkpt/manual-probe.json
```

Each run writes a JSON report under `output/zkpt/` by default with:

- selected artifact profile and proof boundary
- runtime readiness and prover backend
- matched canonical segments
- witness/prove/verify timings
- multi-shard execution metadata for long inputs, including `verifiedShards`, `totalShards`, and `maxParallelShards`
- terminal status: `verified`, `failed`, or `unsupported`
- concrete recommendations when the runtime cannot complete authoritative proofs within budget

### ZKPT latency benchmark

The repo now also includes a latency-analysis command that wraps the live probe and tells you whether the current profile is over the product target budget, what the bottleneck is, and whether source recovery is blocking the next optimization step.

Run it with:

```bash
npm run zkpt:benchmark
```

Useful variant:

```bash
python scripts/zkpt/profile_benchmark.py --stdout-only
```

The benchmark report adds:

- target proof budget
- bottleneck classification (`projection`, `witness`, `prove`, or `verify`)
- over-target signal
- `nextStep`, including the source-recovery gate when the selected profile has no `.circom` source in the workspace

Each verified live workflow now also records a benchmark row in Mongo, and `/status` surfaces the rolling single-proof median as `zkpt_runtime.recentSingleProofBenchmark`.

The current repo truth is now:

- `v4_sparse` is the default authoritative profile
- `v3a` remains the preserved fast full-window baseline
- `v2` remains the preserved heavy authoritative baseline
- the proving step, not witness generation, still dominates latency
- the runtime now supports bounded parallel shard proving for larger multi-shard documents

You can cap shard-level concurrency explicitly:

```bash
$env:BLOCKVAULT_ZKPT_MAX_PARALLEL_SHARDS="2"
```

`/health` and `/status` surface this as `zkpt_runtime.limits.maxParallelShards`.

### Live workflow validation

The repo also includes a packaged-stack workflow runner that exercises the public API end to end:

```bash
npm run zkpt:workflow
```

It performs:

- test login
- case creation
- encrypted document upload
- notarization
- evidence export
- redaction submission
- polling to a terminal verified result
- authoritative ZKPT bundle export

The output JSON is written under `output/zkpt/` and records the end-to-end timings for the currently selected profile.

For scanned/image-only documents, there is also a live OCR workflow runner:
For scanned/image-only documents, the redaction job now performs OCR internally when needed. There is also a live workflow runner for that path:

```bash
npm run zkpt:ocr-workflow
```

It performs:

- test login
- upload of an image-only scanned PDF fixture
- notarization of the original scanned document
- evidence export
- redaction submission and polling through the inline OCR-assisted path
- authoritative ZKPT bundle export

### On-chain verifier configuration

The first on-chain path is single-proof only and uses the generated PLONK verifier plus the receipt registry scaffold in `contracts/zkpt/ZKPTReceiptRegistry.sol`.

Generate the Solidity verifier for the active profile:

```bash
npm run zkpt:export-verifier
```

That writes:

- `contracts/zkpt/generated/<profile>/PlonkVerifier.sol`
- `contracts/zkpt/generated/<profile>/verifier-export.json`

Compile the verifier and registry contracts:

```bash
npm run zkpt:contracts:build
```

Deploy the verifier plus receipt registry on the configured EVM testnet:

```bash
npm run zkpt:contracts:deploy:testnet
```

The deployment helper writes a manifest under:

- `contracts/zkpt/deployments/blockvaultTestnet-<profile>.json`

Configure it with:

```powershell
$env:BLOCKVAULT_ZKPT_ONCHAIN_ENABLED="true"
$env:BLOCKVAULT_ZKPT_ONCHAIN_CHAIN_ID="11155111"
$env:BLOCKVAULT_ZKPT_ONCHAIN_RPC_URL="https://your-sepolia-rpc"
$env:BLOCKVAULT_ZKPT_ONCHAIN_RECEIPT_REGISTRY_ADDRESS="0x..."
$env:BLOCKVAULT_ZKPT_ONCHAIN_RELAYER_PRIVATE_KEY="0x..."
```

When configured, verified single-proof bundles can be submitted through:

- `POST /api/v1/zkpt/bundles/{bundle_id}/submit-onchain`
- `GET /api/v1/zkpt/bundles/{bundle_id}/onchain-status`

`onchainStatus=verified` is intentionally not used. The app only reports `confirmed` after the verifier/registry transaction is actually mined and accepted on-chain.

`/status` also surfaces the on-chain scaffold state as:

- `zkpt_runtime.onchain.verifierSourcePath`
- `zkpt_runtime.onchain.verifierMetadataPath`
- `zkpt_runtime.onchain.verifierContractName`
- `zkpt_runtime.onchain.deploymentManifestPath`
- `zkpt_runtime.onchain.deployedVerifierAddress`
- `zkpt_runtime.onchain.deployedRegistryAddress`

### Restored Circom source

The legacy Circom source for the preserved `v2` profile has now been restored under:

- `circuits/zkpt/v2/src/zkpt_redaction_v2.circom`

There is also a rebuild helper:

```bash
python scripts/zkpt/build_profile.py --help
```

That script is intended to regenerate the baseline profile and produce smaller candidate profiles for benchmarking once `circom`, `snarkjs`, `circomlib`, and a PTAU file are available locally.

The helper now rewrites the top-level `component main = ZKPTRedaction(...)` instantiation for each target profile, so smaller candidate profiles can be generated from the restored `v2` source without manually editing the checked-in baseline source file.


