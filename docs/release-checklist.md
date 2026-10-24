# End-to-End Demo and Release Checklist

Record real results and URLs when this checklist is executed; unchecked items are blockers, not implied successes.

## Source and repository

- [ ] Release SHA is reviewed; all feature branches start from the verified integration baseline.
- [ ] `git diff --check` and CI pass from clean installs.
- [ ] No `.env`, key, database, WAL/SHM, cache, build output, or real patient data is tracked.
- [ ] Clinical ingestion report proves complete pagination/schema validation and nonzero accepted records.
- [ ] MassGIS and clinical-site counts match `backend/data/manifest.json` and committed export metadata.
- [ ] G10 handoff records exact tests, source scope, API behavior, and remaining limitations.

## Railway backend

- [ ] One replica uses Python 3.11 and a persistent `/data` volume.
- [ ] `LLM_PROVIDER=disabled` unless a specifically approved bounded server-side run is planned.
- [ ] `GET /api/health` returns the exact process-liveness contract.
- [ ] `GET /api/trials?page_size=1` returns at least one source-grounded record after provisioning.
- [ ] `GET /api/geo` returns 187 municipality features and honest clinical-site scope/nullability.
- [ ] A bounded `POST /api/optimize` returns a real solver status, constraint checks, provenance, and modeled-not-enrollment caveat.
- [ ] 409/422/429/503 responses use sanitized envelopes; no secrets or local paths are exposed.

## Vercel frontend

- [ ] Root directory is `frontend`; locked install, tests, typecheck, and build pass.
- [ ] Only server-side `TRIALMATCH_API_BASE_URL` points to Railway; browser-visible API URL is unset in production.
- [ ] Patient journey works through Vercel: search, filters/paging, detail, selection, synthetic screening, evidence links, loading/error states.
- [ ] Researcher journey works through Vercel: condition access view, map, optimizer controls, results, baseline, caveats.
- [ ] Keyboard/focus, responsive layouts, contrast/status meaning, and loading/error announcements receive a manual accessibility check.

## Submission

- [ ] Demo contains synthetic profiles only and makes no medical or eligibility claim.
- [ ] Optimizer results are described as modeled outreach coverage, never observed enrollment.
- [ ] Public repository, demo URL, privacy/IP/license review, and sub-three-minute video are complete.
- [ ] Remaining blockers and unavailable external data are stated explicitly.
