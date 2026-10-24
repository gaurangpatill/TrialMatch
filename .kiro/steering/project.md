# TrialMatch Project Steering

## Mission and deadline

Build a source-grounded Hackachusetts 2026 H5 research-access prototype by October 24, 2026 at 6:30 PM Eastern. TrialMatch supports patient-side trial discovery/preliminary screening and researcher-side Massachusetts access analysis/outreach optimization.

## Architecture

Use a modular monolith with Next.js, TypeScript, Tailwind CSS, and MapLibre GL JS in `frontend/`; Python 3.11, FastAPI, and Pydantic in `backend/`; SQLite, pandas, NumPy, and SciPy MILP for storage/computation; pytest and meaningful property-based tests for verification. Do not introduce Kubernetes, Redis, Celery, microservices, or custom model training.

Keep independent boundaries:

- Clinical: `backend/app/clinical/`, `backend/tests/clinical/`, `.kiro/specs/clinical-intelligence/`
- Geography/optimizer: `backend/app/geography/`, `backend/app/optimizer/`, corresponding tests, `.kiro/specs/geo-optimization/`
- Shared changes: coordinate `backend/app/main.py`, contracts, docs, root config, data manifest, and frontend composition.

## Safety and honesty

Use synthetic patient profiles only. Never commit secrets, credentials, private data, PHI, raw caches, generated databases, or unnecessary artifacts. TrialMatch is not a medical device, diagnostic service, medical advice, or definitive eligibility determination. Optimizer results are modeled outreach coverage, not observed enrollment.

Never invent missing source values, observations, contacts, record counts, test outcomes, Kiro usage, screenshots, or integration results. Missing/unsupported clinical information evaluates to `unknown`, never implicitly `met`. Every clinical conclusion must preserve and cite original protocol evidence.

## Data obligations

ClinicalTrials.gov's provided `pageSize=20` URL is incomplete. Consume `nextPageToken` for all pages or record the official challenge ZIP and checksum; fetch detailed study records by NCT ID. The MassGIS query is capped at 100; use `resultOffset`/`resultRecordCount`, count/transfer-limit evidence, and repeated-page guards.

For each source, record exact URL, UTC acquisition time, schema validation, actual counts, duplicates, missing values, source IDs, raw/derived separation, transformations, filters/exclusions, partial failures, and freshness. Keep challenge counts labeled approximate until verified.

## API and reasoning

Follow `contracts/api.md`. Validate requests, source payloads, and configurable LLM output with Pydantic. Cache accepted extraction results. LLMs extract into a limited structure; deterministic code performs three-state `met | not_met | unknown` evaluation. Reject malformed model output. Do not emit unsupported eligibility probabilities.

## Testing and verification

Write tests with implementation on feature branches. Run relevant finite pytest, API/contract, property-based, typecheck, and build checks. Never weaken expectations to obtain green output or report a check not executed. Document failures and unavailable external data honestly.

## Git and Kiro workflow

Keep root `.kiro/` tracked and never ignored. Both developers branch from the same verified shared commit. Stay inside owned paths and coordinate shared-file changes. Read the relevant requirements/design/tasks before implementation, maintain task state honestly, and commit logical checkpoints. Do not fabricate use of Kiro hooks, MCP, Powers, or other capabilities.
