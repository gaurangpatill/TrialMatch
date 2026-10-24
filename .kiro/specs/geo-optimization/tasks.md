# Geographic Intelligence and Optimization Task Plan

Implement on `feature/geo-optimization`. Check a task only after its acceptance evidence is executed. Do not edit clinical-owned paths.

- [x] **G1. Establish geography/source models and persistence boundaries**
  - Define ArcGIS envelopes, normalized block groups, municipalities, source-run metadata, sites, and derived metrics.
  - Define SQLite repository interfaces/schema with explicit null/unit semantics.
  - Test schema validation and aggregate-vs-patient boundaries.
  - _Requirements: R1, R2_

- [x] **G2. Implement complete official MassGIS ingestion**
  - Add metadata/count discovery and offset pagination with transfer-limit/repeated-page guards.
  - Persist/cache source snapshots and acquisition metadata safely.
  - Test multipage, duplicate, malformed, missing-field, partial, and retry behavior.
  - _Requirements: R1_

- [x] **G3. Validate, normalize, and aggregate geography**
  - Preserve source identifiers and required fields; define units and missing handling.
  - Implement documented municipality aggregation without treating missing as zero.
  - Execute a targeted real-source verification when available and record actual counts; document access failure otherwise.
  - _Verified 2026-10-24: `pytest backend/tests/geography -q` passed 19 tests (temporary host validation used Python 3.14/Pydantic 2.12.5 because project Python 3.11 was unavailable). Official client acquisition discovered `OBJECTID`; expected/fetched/unique accepted 2604/2604/2604, duplicates 0, quarantined 0, 27 pages, retries 0, complete; source missingness was `BG_MHHI` 19 and all other required fields 0; normalized 2604 records into 187 municipality EJ-subset aggregates._
  - _Requirements: R1, R2, R5_

- [ ] **G4. Integrate agreed trial-site exchange and access indicators**
  - Consume coordinated site fields without importing clinical internals.
  - Implement transparent deduplication/location resolution and report unresolved sites.
  - Define/version access metrics with assumptions, scale, direction, and tests.
  - _Requirements: R3_

- [ ] **G5. Implement `GET /api/geo`**
  - Return contract-compliant GeoJSON, null geometry when unavailable, raw/derived labels, and freshness.
  - Add success, filter, missing-geometry, validation, and source-summary API tests.
  - _Requirements: R2, R3, R5_

- [ ] **G6. Implement MILP input and formulation**
  - Validate candidates, units, finite costs/weights, budget, limits, and supported constraints.
  - Build deterministic variable mappings, objective vector, bounds, integrality, and constraint matrix.
  - Test manually solvable, infeasible, boundary, unknown-ID, and malformed inputs.
  - _Requirements: R4_

- [ ] **G7. Implement solver interpretation and baseline**
  - Invoke SciPy MILP and map all termination states honestly.
  - Compute selected resources/objective from validated inputs and implement deterministic constrained baseline.
  - Add property-based budget/count invariants, tie behavior, determinism, and baseline comparison tests.
  - _Requirements: R4, R5_

- [ ] **G8. Implement `POST /api/optimize`**
  - Return exact contract fields, assumptions, model-vs-observed caveat, solver metadata, and infeasible behavior.
  - Add API/contract tests and wire routers only through shared composition.
  - _Requirements: R4, R5_

- [ ] **G9. Build researcher dashboard integration**
  - Use MapLibre with accessible source/derived layers, legends, no-data state, freshness, and limitations.
  - Integrate optimization inputs/results without implying enrollment prediction.
  - Run frontend typecheck/build and critical interaction verification.
  - _Requirements: R3, R5_

- [ ] **G10. Workstream verification and handoff**
  - Run complete geographic/optimizer pytest suites and frontend checks; record exact commands/results.
  - Reconcile observed source counts and provenance; distinguish fixtures from actual records.
  - Update limitations and Kiro usage with facts only.
  - Commit stable checkpoint and communicate site exchange/API behavior to integration owners.
  - _Requirements: R1–R5_

## Completion gate

Successful solutions must satisfy validated constraints, source completeness/failures must be explicit, and APIs must honor `contracts/api.md`. Reduce geographic breadth or visual polish before compromising provenance, mathematical validity, or honest interpretation.
