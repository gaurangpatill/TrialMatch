# TrialMatch Deployment

TrialMatch deploys as one FastAPI process on Railway and one Next.js project on Vercel. These steps configure a hackathon prototype, not a regulated or highly available clinical system.

## Railway: FastAPI

`pyproject.toml` keeps the tested Python 3.11 combination `numpy==2.2.4` and `scipy==1.15.2`; the complete local backend suite exercised the SciPy MILP successfully. Do not independently upgrade one of these pins during release.

1. Create a Railway service from this repository. `railway.json` selects Nixpacks, Python from `.python-version`, the FastAPI start command, and `/api/health` as a liveness check.
2. Keep **one replica**. SQLite and the in-process optimizer limiter are not distributed systems.
3. Attach a persistent volume mounted at `/data`. Set:

```text
TRIALMATCH_DATABASE_URL=sqlite:////data/trialmatch.sqlite3
CLINICALTRIALS_CACHE_DIR=/data/cache/clinicaltrials
CLINICALTRIALS_API_BASE_URL=https://clinicaltrials.gov/api/v2
CLINICALTRIALS_REQUEST_TIMEOUT_SECONDS=30
CLINICALTRIALS_MAX_RETRIES=3
TRIALMATCH_SITE_EXPORT_PATH=backend/data/exports/ma_trial_sites.json
LLM_PROVIDER=disabled
```

Do not set `LLM_API_KEY` unless a specific server-side run is authorized. Never expose it through a `NEXT_PUBLIC_*` variable.

### Provision the clinical database

The database and caches are intentionally not committed. A fresh volume has an empty schema and patient search is not release-ready until a complete source ingestion succeeds. Run this once in a Railway shell/job before promotion:

```bash
python -m backend.app.clinical.cli ingest \
  --database /data/trialmatch.sqlite3 \
  --cache-dir /data/cache/clinicaltrials \
  --page-size 1000 \
  --detail-limit 0 \
  --report /data/cache/clinicaltrials/latest_ingestion_report.json
```

This command follows all `nextPageToken` pages. It intentionally does not fetch expanded records by default during provisioning. Retain the report on the volume and require `status=complete`, `pagination_completed=true`, nonzero accepted records, and reconciled counts. Then smoke `GET /api/trials?page_size=1`. Live source results change over time, so this is reproducible acquisition logic—not byte-identical restoration. A checksum-pinned official snapshot is still unavailable.

Expanded demonstration records can be fetched later only with explicit IDs/conditions and bounded limits. Never run paid summary/extraction commands in bulk.

`GET /api/health` proves only that the process responds. It does not prove that SQLite is populated, source data is fresh, or optimization succeeds.

## Vercel: Next.js

1. Import the same repository and set **Root Directory** to `frontend`.
2. Use Node 20, install command `npm ci`, and build command `npm run build`.
3. Set the server-only variable:

```text
TRIALMATCH_API_BASE_URL=https://YOUR-RAILWAY-SERVICE.example
```

Leave `NEXT_PUBLIC_API_BASE_URL` unset in production. `frontend/next.config.ts` proxies `/api/geo` and `/api/optimize` through the Vercel origin, while existing clinical route handlers proxy patient requests. This keeps the Railway URL out of browser configuration and avoids permissive production CORS.

## Security and operational boundary

- `.env`, SQLite/WAL/SHM files, API caches, `.next`, and `node_modules` must remain untracked.
- FastAPI permits only local-development CORS origins. Same-origin Vercel proxying is the production path; CORS is not authentication.
- The public hackathon API is unauthenticated. Do not submit real patient data or PHI. Profiles must be synthetic and request bodies must not be logged.
- Swagger/OpenAPI endpoints are public unless Railway networking is restricted. Confirm that exposure is intentional.
- The process-local optimizer limiter resets on restart and differs per replica. It is a bounded prototype control, not abuse protection.
- No load, penetration, disaster-recovery, legal, clinical, privacy, or production accessibility review has been completed.
