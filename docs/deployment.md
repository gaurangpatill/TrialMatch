# TrialMatch deployment: Render + Vercel

TrialMatch deploys as one Render FastAPI web service and one Vercel Next.js project. The Vercel site owns `/`, `/patient`, and `/researcher`. This is a hackathon research prototype, not a regulated or highly available clinical system.

## Render: FastAPI and persistent SQLite

### Create the service

1. In Render, choose **New > Blueprint**, connect GitHub, and select `gaurangpatill/TrialMatch`.
2. Use branch **`integration/final-app`**. `render.yaml` is at the repository root; do not set a subdirectory as the root.
3. The blueprint follows Render's [Blueprint YAML reference](https://render.com/docs/blueprint-spec) and creates a Python web service named `trialmatch-api` with:
   - Runtime: Python **3.11.14** (`PYTHON_VERSION=3.11.14`; also pinned by `.python-version`).
   - Build: `python -m pip install .`
   - Start: `python -m uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT --log-level info`
   - Health check: `/api/health`
   - Plan: **0.5 CPU / 512 MB (`0.5c-512mb`) or higher**, one instance. This is the current minimum paid compute option in the Render Blueprint schema; a free service is not suitable because the clinical SQLite file requires a persistent disk.
   - Disk: `trialmatch-data`, **1 GB**, mounted at `/var/data` ([Render persistent disk guidance](https://render.com/docs/disks)).
4. Confirm the generated service URL is HTTPS, for example `https://trialmatch-api-ACCOUNT.onrender.com`. The exact hostname is account-generated.

The blueprint sets these non-secret values:

```text
TRIALMATCH_ENV=production
TRIALMATCH_DATABASE_URL=sqlite:////var/data/trialmatch.sqlite3
TRIALMATCH_SITE_EXPORT_PATH=backend/data/exports/ma_trial_sites.json
CLINICALTRIALS_API_BASE_URL=https://clinicaltrials.gov/api/v2
CLINICALTRIALS_REQUEST_TIMEOUT_SECONDS=30
CLINICALTRIALS_MAX_RETRIES=3
CLINICALTRIALS_CACHE_DIR=/var/data/cache/clinicaltrials
LLM_PROVIDER=disabled
```

`TRIALMATCH_DATABASE_URL` is the actual variable read by `backend/app/clinical/dependencies.py`. Four slashes are required for the absolute `/var/data/...` SQLite path. Geography uses the committed, validated site and municipality snapshots; the large clinical database is separate.

### Provision the ignored database safely

`backend/data/trialmatch.sqlite3` is intentionally ignored by Git and is **not** in the deployment image. A healthy process initially proves only that FastAPI responds; it does not prove that any studies exist.

After the disk is attached, open the Render service Shell and run this once from the repository root:

```bash
python -m backend.app.clinical.cli ingest \
  --database /var/data/trialmatch.sqlite3 \
  --cache-dir /var/data/cache/clinicaltrials \
  --page-size 1000 \
  --detail-id NCT01521741 \
  --detail-id NCT01790152 \
  --report /var/data/cache/clinicaltrials/latest_ingestion_report.json
```

This follows `nextPageToken` through the current recruiting-Massachusetts result set, validates the records, and fetches detailed official records only for the two named demonstrations. Do not substitute a copied local database unless you have separately approved a secure transfer and verified its provenance. Require the command output to report `status: "complete"`, `pagination_completed: true`, zero unexplained exclusions/errors, both requested details retrieved, and an observed nonzero accepted count. The count is source-time dependent; do not assume it is 3,145.

Verify the stored database without printing contacts or other source payloads:

```bash
python -c 'import sqlite3; p="/var/data/trialmatch.sqlite3"; c=sqlite3.connect(p); print("studies", c.execute("select count(*) from studies").fetchone()[0]); print(c.execute("select nct_id, detail_status, length(source_description) from studies where nct_id in (?,?) order by nct_id", ("NCT01521741","NCT01790152")).fetchall())'
```

Then verify the deployed API, replacing the generated hostname:

```bash
curl -fsS https://YOUR-RENDER-HOST/api/health
curl -fsS https://YOUR-RENDER-HOST/api/trials/NCT01521741
curl -fsS https://YOUR-RENDER-HOST/api/trials/NCT01790152
curl -fsS 'https://YOUR-RENDER-HOST/api/geo?access_radius_km=40'
```

The two detail responses must contain nonblank source-backed description fields. Record the observed study count, manually restart the Render service, rerun the read-only Python query, and confirm the count and both rows are unchanged. That verifies persistence across a restart; the health endpoint alone does not.

### Optional bounded OpenAI summaries

Keep inference server-side. To generate summaries for only the approved demonstration studies, add these Render secrets/settings yourself:

```text
LLM_PROVIDER=openai-compatible
LLM_MODEL=gpt-4.1-mini
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=<your Render secret; never commit or expose as NEXT_PUBLIC_*>
```

Then run exactly:

```bash
python -m backend.app.clinical.cli summarize --database /var/data/trialmatch.sqlite3 --nct-id NCT01521741 --nct-id NCT01790152
```

The command accepts at most three explicit unique IDs and caches validated output against each current source hash. Search and detail HTTP requests never trigger paid inference. Return `LLM_PROVIDER` to `disabled` afterward if no further explicitly authorized maintenance run is needed; cached summaries remain readable.

### API and CORS boundary

Keep one Render instance because SQLite and the process-local optimizer controls are not distributed. FastAPI currently allows local-development CORS origins only. Production browsers should not call Render directly: Vercel proxies requests server-side/same-origin over HTTPS. The public Render API is still unauthenticated; never send real patient data or PHI and do not log request bodies.

## Vercel: one Next.js website

1. Import GitHub repository **`gaurangpatill/TrialMatch`** into one Vercel project.
2. Select production branch **`integration/final-app`** and root directory **`frontend`**.
3. Framework preset: **Next.js**. Use Node **20.x**, install command `npm ci`, build command `npm run build`, and the standard Next.js output (do not set a static export directory).
4. Add one production environment variable, using the actual generated Render HTTPS origin and no trailing path:

```text
TRIALMATCH_API_BASE_URL=https://YOUR-RENDER-HOST
```

Do **not** copy local `.env`, do not set `NEXT_PUBLIC_API_BASE_URL` in production, and do not put the OpenAI key in Vercel. `TRIALMATCH_API_BASE_URL` is read only by Next.js server route handlers and build-time rewrites.

The resulting single Vercel origin serves:

- `/` — TrialMatch entry page
- `/patient` — Participant Portal
- `/researcher` — Researcher Workspace

Participant `/api/trials`, `/api/trials/:nctId`, and `/api/match` requests go through validated Next.js route handlers. Researcher `/api/geo` and `/api/optimize` requests use `frontend/next.config.ts` same-origin rewrites to Render. Browser URLs remain on Vercel; Vercel contacts Render over HTTPS. `frontend/public/maplibre-gl-worker.mjs` is served as `/maplibre-gl-worker.mjs`, so no worker CDN or browser secret is required.

After deployment, open all three routes, search for and open `NCT01521741` and `NCT01790152`, verify their descriptions, run a fictional-profile comparison, load the access map, change miles, and run one outreach plan. Check browser Network requests remain on the Vercel origin and that the worker returns HTTP 200. WebGL, third-party map tiles, and sticky/sidebar behavior still require real-browser verification.

## Release boundary

Do not upload `.env`, SQLite/WAL/SHM files, caches, or credentials through Git. Do not claim a deployed study count until the Render volume query and deployed endpoints have been observed. Do not change billing or production settings automatically; the account owner must create the paid service, disk, secrets, and generated URLs.
