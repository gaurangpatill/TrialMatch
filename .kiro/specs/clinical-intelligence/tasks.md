# Clinical Intelligence Task Plan

Implement on `feature/clinical-intelligence`. Check a task only after its acceptance evidence is executed. Do not edit geographic/optimizer-owned paths.

- [x] **C1. Establish clinical domain models and persistence boundaries**
  - Define normalized study, source/provenance, criterion, synthetic profile, and result models.
  - Define SQLite repository interfaces/schema and migration/bootstrap behavior.
  - Verify Pydantic validation, null semantics, source evidence, and synthetic-only rejection.
  - _Requirements: R2, R3, R5_

- [x] **C2. Implement official source adapters and pagination**
  - Add ClinicalTrials.gov list pagination with token-loop protection and bounded retries.
  - Add selected detailed-study retrieval and atomic cache behavior.
  - Add challenge ZIP adapter if an official file is available.
  - Test multiple pages, duplicates, transient failures, malformed/missing fields, and partial-run reports.
  - _Requirements: R1, R2_

- [x] **C3. Normalize and persist studies with provenance**
  - Preserve identifiers, protocol eligibility text, facilities, locations, provided contacts, source URL, and retrieval time.
  - Record observed counts, duplicates, missing values, filters/exclusions, and acquisition status.
  - Verify a targeted real-source run when access is available; document failure otherwise.
  - _Requirements: R1, R2, R6_

- [x] **C4. Implement `GET /api/trials`**
  - Add deterministic filters/pagination and Pydantic response models.
  - Add success, validation, empty-result, freshness, and shared-error contract tests.
  - _Requirements: R2, R6_

- [ ] **C5. Implement structured extraction boundary**
  - Define supported vocabulary, provider protocol/configuration, prompt/schema versioning, and cache key.
  - Validate provider JSON strictly; preserve source text and uncertainty; reject malformed/unsupported shapes.
  - Add disabled/unavailable provider and cache fallback behavior.
  - Test invalid responses, source preservation, cache invalidation, and provider unavailability.
  - Implementation and mocked-provider tests pass; a real curated LLM run remains blocked until a provider, model, base URL, and credential are configured.
  - _Requirements: R3, R6_

- [x] **C6. Implement pure three-state evaluator**
  - Implement inclusion/exclusion polarity, negation, numeric and age bounds, bounded durations, supported compounds, and unknown handling.
  - Surface unsupported and contradictory criteria.
  - Add table-driven and property-based tests for boundaries, determinism, missing facts, polarity, compounds, and order invariance.
  - _Requirements: R4, R6_

- [x] **C7. Implement synthetic matching and explanations**
  - Aggregate criterion states without probabilities.
  - Generate evidence-linked deterministic explanations, unresolved requirements, and missing questions.
  - Ensure wording does not contradict protocol text and always includes medical limitations.
  - Test known mismatches, potential matches, unresolved cases, and contradictory evidence.
  - _Requirements: R4, R5, R6_

- [x] **C8. Implement `POST /api/match` and wire clinical router**
  - Conform exactly to shared request, response, enum, and error contracts.
  - Confirm matching does not require a live provider when valid cache exists.
  - Add API/contract tests and register only through the shared composition boundary.
  - _Requirements: R5, R6_

- [x] **C9. Workstream verification and handoff**
  - Run targeted and complete clinical pytest suites; record exact commands/results.
  - Verify provenance against observed data and distinguish fixtures from real records.
  - Update limitations and Kiro usage with facts only.
  - Commit a stable checkpoint and communicate API behavior/source freshness to integration owners.
  - _Requirements: R1–R6_

## Completion gate

All required tests must execute, source failures must be documented, `contracts/api.md` must be honored, and no output may imply confirmed eligibility. Breadth may be reduced to a selected detailed-study cohort; correctness, unknown handling, and evidence traceability may not.
