# Clinical Intelligence

Owned by Developer A on `feature/clinical-intelligence`. This package separates official source access, normalization, SQLite persistence, strict extraction, pure three-state evaluation, matching, and HTTP routing.

## Real ingestion

From the repository root with the Python 3.11 environment active:

```bash
python -m backend.app.clinical.cli ingest \
  --page-size 1000 \
  --detail-limit 20 \
  --update-manifest backend/data/manifest.json
```

The command follows `nextPageToken` to completion, rejects repeated tokens, records duplicates/missing values/exclusions, fetches selected detailed studies, caches successful details, writes a local ignored SQLite database, and updates only the clinical manifest entry when explicitly requested.

The verified 2026-10-24 run is recorded in `backend/data/manifest.json`: 3,145 source records across four pages, 3,145 accepted, zero duplicate NCT IDs, zero excluded records, and 20 detailed records. Counts are source observations at that acquisition time, not permanent guarantees.

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

Provider JSON must pass strict Pydantic validation, preserve exact criterion text found in the protocol, use the supported predicate vocabulary, and match the source NCT ID. Accepted output is cached by source hash, schema/prompt version, provider, and model. A valid cache remains usable if that provider later becomes unavailable.

Structured source age/sex fields are independently converted into deterministic criteria; they are labeled `source_structured`, never represented as LLM output.

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
