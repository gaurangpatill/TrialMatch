# TrialMatch Agent and Ownership Guide

This file defines repository boundaries for humans and AI coding agents. The October 24, 2026 internal deadline is 6:30 PM Eastern.

## Non-negotiable rules

- Use only synthetic patient profiles. Never commit personal, protected health, credential, or secret data.
- Preserve original source identifiers and evidence. Do not fabricate observations, counts, eligibility facts, Kiro usage, tests, screenshots, or integration results.
- Treat matching as preliminary screening, not medical advice or confirmed eligibility.
- Treat optimizer output as modeled outreach coverage, not observed enrollment.
- Keep `.kiro/` tracked. Do not add `.kiro/` to ignore rules.
- Validate all external schemas and model-generated structures at trust boundaries.
- Missing clinical information produces `unknown`, never an implied match.
- Do not alter shared API contracts without coordinating both developers.

## Branches and ownership

Both feature branches must start from the same verified scaffold commit on `main`.

### Developer A — `feature/clinical-intelligence`

Exclusive implementation ownership:

- `backend/app/clinical/`
- `backend/tests/clinical/`
- `.kiro/specs/clinical-intelligence/`

Responsibilities: ClinicalTrials.gov ingestion, detailed-record caching, eligibility extraction, deterministic three-state evaluation, synthetic patient matching, evidence-linked explanations, clinical endpoints, and clinical tests.

### Developer B — `feature/geo-optimization`

Exclusive implementation ownership:

- `backend/app/geography/`
- `backend/app/optimizer/`
- `backend/tests/geography/`
- `backend/tests/optimizer/`
- `.kiro/specs/geo-optimization/`

Responsibilities: MassGIS ingestion, municipality aggregation, site/access analysis, SciPy MILP outreach optimization, baseline comparison, researcher dashboard, and geographic/optimizer tests.

Neither developer modifies the other workstream's owned paths.

## Shared paths

Shared paths include `README.md`, `AGENTS.md`, `.gitignore`, `.env.example`, `pyproject.toml`, `backend/app/main.py`, `backend/data/manifest.json`, `contracts/`, `docs/`, and common frontend composition/configuration.

To change a shared path:

1. Describe the proposed contract or integration change in the handoff/PR.
2. Confirm impact with the other owner before frontend integration begins.
3. Keep the change narrowly scoped and backward compatible where possible.
4. Update documentation and tests that encode the shared behavior.
5. Rebase or merge the latest shared integration state before final verification.

## Development workflow

1. Read the relevant Kiro requirements, design, and tasks documents.
2. Mark only actively started tasks as in progress using the conventions in the spec.
3. Implement within owned directories.
4. Add focused tests alongside behavior; use property-based tests only where invariants benefit.
5. Run actual targeted checks and record only observed results.
6. Commit logical checkpoints. Do not bypass hooks or overwrite teammate work.
7. Document blocked data access instead of silently substituting synthetic source records.

## Definition of done

A workstream is not operational until its implementation, source validation, contract compliance, tests, limitations, and reproducibility steps have been executed. At feature freeze, prioritize correctness, uncertainty, and traceability over breadth or visual polish.
