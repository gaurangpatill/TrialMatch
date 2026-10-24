# Clinical Intelligence

Owned by Developer A on `feature/clinical-intelligence`. This package separates official source access, normalization, SQLite persistence, strict extraction, pure three-state evaluation, matching, and HTTP routing.

## Real ingestion

From the repository root with the Python 3.11 environment active:

```bash
python -m backend.app.clinical.cli ingest \
  --page-size 1000 \
  --detail-limit 100 \
  --detail-condition cancer \
  --detail-delay-seconds 0.25 \
  --update-manifest backend/data/manifest.json
```

The command follows `nextPageToken` to completion, rejects repeated tokens, records duplicates/missing values/exclusions, fetches selected detailed studies, caches successful details, writes a local ignored SQLite database, and updates only the clinical manifest entry when explicitly requested.

The verified 2026-10-24 run is recorded in `backend/data/manifest.json`: 3,145 source records across four pages, 3,145 accepted, zero duplicate NCT IDs, zero excluded records, and 100 detailed cancer-related records selected deterministically by NCT ID. Counts are source observations at that acquisition time, not permanent guarantees.

## Massachusetts recruiting-site export

Generate the committed geographic handoff from the expanded local records:

```bash
python -m backend.app.clinical.cli export-sites \
  --output backend/data/exports/ma_trial_sites.json \
  --cohort-description "100 cancer-related recruiting studies selected deterministically by NCT ID from title/condition matches; expanded from the 3,145-study Massachusetts recruiting snapshot acquired 2026-10-24"
```

`backend/data/exports/ma_trial_sites.json` contains metadata, primary `records`, and one-to-one `geography_records`. The latter exactly matches the geographic branch's strict `TrialSite` fields; the primary records additionally expose required `coordinate_status` and source facility recruitment status.

The generated artifact contains 149 explicitly Massachusetts, site-level `RECRUITING` facilities across 86 NCT IDs and 72 normalized facility/location tuples. All 149 have source-provided coordinate pairs; no geocoding was performed. The exporter preserves unresolved facilities when encountered, but this cohort contains zero. It excludes and counts inactive/unknown site statuses and missing facility names. This is a partial cancer-focused 100-study detail cohort, not complete Massachusetts geographic coverage.

## Strict extraction

By default `LLM_PROVIDER=disabled`. An OpenAI-compatible schema-guided provider is available when these environment values are supplied:

```text
LLM_PROVIDER=openai-compatible
LLM_MODEL=<model identifier>
LLM_BASE_URL=<provider API base URL>
LLM_API_KEY=<secret, never commit>
```

Run a bounded curated extraction:

```bash
python -m backend.app.clinical.cli extract --limit 20
```

Provider JSON must pass strict Pydantic validation, use deterministic `item-NNN` identifiers for every non-heading source line, preserve exact criterion and uncovered-item text found in the protocol, use the supported predicate vocabulary, match the source NCT ID, and explicitly reconcile every segmented protocol item as accounted or uncovered. Obvious multi-clause source lines require an explicit supported compound or unsupported predicate; provider-declared completeness remains partial until a separate persisted `manual_protocol_review` approval is recorded. A successful provider response or nonzero rule count never proves complete coverage. Accepted output is published atomically with criteria and cached by source hash, schema/prompt version, provider, and model; only after success are superseded generations removed. Invalid, unavailable, or failed refreshes preserve the previous accepted generation, while source-hash filtering prevents stale rules from being evaluated.

Structured source age/sex fields are independently converted into deterministic criteria; they are labeled `source_structured`, never represented as LLM output, and never establish full-protocol coverage. Matching remains `unresolved` unless current-source coverage is explicitly complete and all supported criteria are met; a reliable mismatch remains reportable under incomplete coverage.

No LLM environment variables or credentials were available during the October 24 readiness audit, so no live extraction is claimed. A human must provide all four values above and authorize a bounded `--limit 3` to `--limit 5` run before any extraction is represented as live.

## APIs

- `GET /api/trials`: deterministic local search/filter/pagination; never triggers extraction.
- `POST /api/match`: accepts only explicitly synthetic profiles and returns `met`, `not_met`, or `unknown` criterion evidence.

Start the API after ingestion:

```bash
uvicorn backend.app.main:app --reload
```

## Verification

```bash
pytest backend/tests/clinical -q
```

Tests use explicit synthetic/source-shaped fixtures and mocked providers. They do not claim live LLM execution or replace the observed source run.
