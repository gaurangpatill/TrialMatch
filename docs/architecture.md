# Architecture

## Decision summary

TrialMatch uses a modular monolith: one Next.js web application, one FastAPI process, one SQLite database, and three internal backend domains. This keeps deployment and hackathon operations simple while preserving boundaries for parallel development.

## Runtime view

```text
Browser
  │
  ▼
Next.js + TypeScript + Tailwind + MapLibre
  │ JSON over /api/*
  ▼
FastAPI composition root (backend/app/main.py)
  ├── Clinical Intelligence
  ├── Geographic Intelligence
  └── Outreach Optimizer
       │
       ├── SQLite repositories/cache metadata
       ├── pandas / NumPy transforms
       └── SciPy MILP

External read-only sources:
  ClinicalTrials.gov API v2 ──► Clinical Intelligence
  MassGIS ArcGIS EJ2020 ──────► Geographic Intelligence
  Configured LLM provider ────► Clinical extraction only
```

## Module boundaries

### Clinical Intelligence

Owns ClinicalTrials.gov access, normalized studies, extracted criterion structures, deterministic three-state evaluation, synthetic profiles, matching, and evidence-linked results. It must not import geographic or optimizer internals. Its public integration surface is `GET /api/trials` and `POST /api/match`.

### Geographic Intelligence

Owns MassGIS access, aggregate block-group/municipality models, trial-site geographic transforms, access indicators, and map-ready responses. It consumes only agreed clinical site data or shared contract models—not clinical implementation internals. Its public surface is `GET /api/geo`.

### Outreach Optimizer

Owns optimization inputs, constraints, objective terms, SciPy MILP formulation, feasibility/error handling, and baseline comparison. It may depend on stable geographic domain interfaces. Its public surface is `POST /api/optimize`.

### Shared composition

`backend/app/main.py`, environment configuration, API versioning, database initialization, CORS/deployment configuration, shared docs, and frontend routing are coordinated paths. Domain code should expose routers/services that the composition root wires together; domains should not register themselves through side effects.

## Data flow and storage

1. Ingestion writes immutable or content-addressed raw responses to ignored local storage and records provenance.
2. Schema validation converts source records into normalized domain models while preserving source IDs and source text.
3. Derived tables/caches are distinguishable from raw inputs and reproducible from documented source snapshots.
4. SQLite stores normalized records, extraction caches, and run metadata. SQLite database files are never committed.
5. APIs return Pydantic-validated structures conforming to `contracts/api.md`.

The source manifest is tracked at `backend/data/manifest.json`. Acquisition-specific observed counts and timestamps must replace `null` only after ingestion has actually occurred.

## Trust boundaries

External APIs, ZIP files, LLM responses, environment values, and browser requests are untrusted. Validate at entry with source-schema checks or Pydantic. Preserve malformed source records for audit when safe, report failures, and never fill unavailable fields with invented values.

LLM output is an extraction proposal—not a clinical decision. It must pass schema validation and use a limited criterion vocabulary. The deterministic evaluator alone maps available synthetic facts to `met`, `not_met`, or `unknown`.

## API and frontend integration

The shared contract uses JSON, snake_case field names, ISO 8601 UTC timestamps, source URLs, and stable enum values. Breaking changes require both workstream owners to coordinate and update `contracts/api.md` before implementation. MapLibre is frontend-only; server responses remain provider-neutral GeoJSON or documented JSON.

## Error and observability policy

- API errors use the shared error envelope and a request ID.
- Source failures include source, operation, retryability, and safe details; secrets are never logged.
- Ingestion runs record start/end timestamps, requested filters, pagination completion, observed counts, duplicates, missing fields, and exclusions.
- Optimizer runs report feasibility and assumptions; matching reports unresolved criteria and limitations.

## Deployment assumptions

The prototype targets one frontend deployment and one Python backend with persistent SQLite storage appropriate to a single instance. Multi-writer scale, distributed jobs, and production clinical operations are explicitly out of scope. Any public demo must use synthetic profiles and environment-provided secrets.
