# Clinical Intelligence Requirements

## Scope

Developer A implements this spec on `feature/clinical-intelligence`, not `main`. The workstream owns ClinicalTrials.gov ingestion, eligibility extraction, deterministic evaluation, synthetic patient matching, explanations, clinical APIs, and tests.

## Requirements

### R1 — Verifiable study ingestion

**User story:** As a project reviewer, I want recruiting Massachusetts studies acquired from the official source so that trial claims are reproducible.

Acceptance criteria:

1. WHEN API ingestion runs, THE SYSTEM SHALL follow ClinicalTrials.gov API v2 `nextPageToken` pagination until the token is absent, and SHALL reject repeated-token loops.
2. WHEN a challenge starter ZIP is available, THE SYSTEM SHALL support it without claiming API acquisition and SHALL record filename, checksum, acquisition time, schema, and observed count.
3. THE SYSTEM SHALL retrieve selected detailed records by NCT ID, preserve source URLs/UTC timestamps, retry transient failures with bounds, and cache successful records.
4. THE SYSTEM SHALL preserve NCT IDs, reject or explicitly resolve duplicates, validate source shape, track missing fields, and document filtering/exclusions.
5. IF acquisition is partial or unavailable, THEN THE SYSTEM SHALL expose/document the failure and SHALL NOT substitute fabricated source observations.

### R2 — Normalized study records

**User story:** As a patient portal, I want stable study structures so that search and matching do not depend on raw API shape.

Acceptance criteria:

1. THE SYSTEM SHALL normalize title, status, conditions, phase, eligibility text, age bounds, sex restriction, facilities/locations, provided contacts, source URL, and retrieval timestamp.
2. WHEN source values are missing, THE SYSTEM SHALL preserve null/empty semantics rather than infer values.
3. THE SYSTEM SHALL distinguish raw source text from derived parsed fields.
4. `GET /api/trials` SHALL follow `contracts/api.md` with deterministic pagination.

### R3 — Schema-validated eligibility extraction

**User story:** As a matching engine, I want limited structured rules with original evidence so that deterministic evaluation is auditable.

Acceptance criteria:

1. THE SYSTEM SHALL preserve criterion text, inclusion/exclusion class, supported attribute, operator, comparison value, temporal qualifier when present, NCT ID, and defensible uncertainty metadata.
2. THE SYSTEM SHALL validate every provider response with Pydantic and reject malformed output.
3. THE SYSTEM SHALL map only an explicit supported vocabulary; complex or unsupported concepts SHALL remain unknown/unstructured.
4. THE SYSTEM SHALL cache accepted extractions using study/source version and extraction schema/model identity.
5. IF the LLM provider is disabled or unavailable, THEN cached structured criteria and deterministic functionality SHALL remain usable, and uncached extraction SHALL fail safely.

### R4 — Deterministic three-state evaluation

**User story:** As a user, I want cautious and repeatable criterion results so that missing facts are not portrayed as eligibility.

Acceptance criteria:

1. THE SYSTEM SHALL return exactly `met`, `not_met`, or `unknown` per criterion.
2. Missing, unsupported, ambiguous, or insufficiently dated facts SHALL evaluate to `unknown`.
3. A failed inclusion and a satisfied exclusion SHALL produce a known mismatch with correct polarity.
4. THE SYSTEM SHALL correctly handle supported negation, numeric ranges, inclusive/exclusive age boundaries, bounded durations, and supported compound logic.
5. Repeated evaluation of identical validated inputs SHALL produce identical results independent of LLM availability.
6. Contradictory criteria SHALL be surfaced, not silently reconciled into a match.

### R5 — Synthetic patient matching

**User story:** As a patient-portal demonstrator, I want source-linked preliminary results for synthetic profiles so that I can understand matches, mismatches, and open questions.

Acceptance criteria:

1. THE SYSTEM SHALL reject a profile unless `synthetic` is true.
2. `POST /api/match` SHALL return potential matches, known mismatches, unresolved requirements, criterion-level explanations, missing questions, source links, and a medical limitation disclaimer.
3. THE SYSTEM SHALL NOT emit numerical eligibility probabilities or confirmed-eligibility language.
4. Every conclusion SHALL link to preserved criterion evidence and SHALL not contradict original protocol wording.
5. IF evidence is insufficient, THEN the explanation SHALL state that explicitly.

### R6 — Verification and operational honesty

Acceptance criteria:

1. Tests SHALL cover missing facts, boundary ages, inclusion/exclusion polarity, negation, compounds, bounded durations, unsupported criteria, malformed LLM output, duplicate IDs, missing API fields, evidence preservation, determinism, provider fallback, and contradictory criteria.
2. Property-based tests SHALL be used where they materially validate invariants such as determinism and boundaries.
3. API/contract tests SHALL validate `GET /api/trials`, `POST /api/match`, and shared error shapes.
4. No endpoint, ingestion count, extraction, or test SHALL be represented as operational until executed and verified.

## Out of scope

Real patient data, medical validation, confirmed eligibility, unbounded model calls across all studies, clinical recommendations, custom model training, and modifications to geographic/optimizer-owned modules.
