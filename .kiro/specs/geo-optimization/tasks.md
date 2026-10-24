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

- [x] **G4. Integrate agreed trial-site exchange and access indicators**
  - Consume coordinated site fields without importing clinical internals.
  - Implement transparent deduplication/location resolution and report unresolved sites.
  - Define/version access metrics with assumptions, scale, direction, and tests.
  - _Verified 2026-10-24 with Python 3.11.10 and pinned dependencies: `pytest backend/tests/geography backend/tests/optimizer -q` passed 81 tests; matching `compileall` passed. The strict external clinical-site adapter, deterministic deduplication, explicit recruiting-only/Massachusetts/condition filters, unresolved reporting, nearest-site distance, and distinct nearby-NCT counts are fixture-tested; no live clinical-site export was available or claimed._
  - _Official MassGIS geometry run: 2604/2604 unique EJ block groups over 6 pages, zero duplicates/missing/invalid geometry, polygon-centroid fallback for 2604 features, and 187 resolved/0 unresolved municipality representative analytical points. Snapshot: `backend/app/geography/data/municipality_ej_representative_points.json` (81,866 bytes). Genuine SciPy 1.15.2 scenario (187 included, 0 excluded; equal abstract unit cost, budget/events 3, 25 km, lambda 0.6) was optimal/native 0/gap 0.0, selected Hudson/Reading/Sharon, objective 1,639,905.9010591828, covered EJ-subset population proxy 2,636,354 across 87 communities; both greedy baselines selected Clinton/Reading/Walpole, objective 1,636,717.6488802643, population 2,628,696 across 85 communities._
  - _Requirements: R3_

- [x] **G5. Implement `GET /api/geo`**
  - Return contract-compliant GeoJSON, null geometry when unavailable, raw/derived labels, and freshness.
  - Add success, filter, missing-geometry, validation, and source-summary API tests.
  - _Verified 2026-10-24 with Python 3.11.10, FastAPI 0.115.12, Pydantic 2.10.6, and SciPy 1.15.2: the combined geography/optimizer suite passed 104 tests and geography compileall passed. Actual TestClient `GET /api/geo` returned HTTP 200 with 187 deterministic municipality Point features, 187 resolved/0 unresolved, genuine MassGIS source/provenance and EJ-subset fields; with no export present, availability was false and all clinical/access counts and feature access values were null. Export tests cover array/records/items/sites envelopes, nullable aliases, status normalization, coordinate quarantine, contradictory country/state quarantine, filtering, and reconciled counts._
  - _Requirements: R2, R3, R5_

- [x] **G6. Implement MILP input and formulation**
  - Validate candidates, units, finite costs/weights, budget, limits, and supported constraints.
  - Build deterministic variable mappings, objective vector, bounds, integrality, and constraint matrix.
  - Test manually solvable, infeasible, boundary, unknown-ID, and malformed inputs.
  - _Verified 2026-10-24 with temporary Python 3.11.10 and pinned SciPy 1.15.2: `PYTHONPATH=/tmp/trialmatch-geotest311:. /tmp/trialmatch-python/python/bin/python3 -m pytest backend/tests/optimizer -q` passed 53 tests; `PYTHONPATH=/tmp/trialmatch-geotest311:. /tmp/trialmatch-python/python/bin/python3 -m compileall -q backend/app/optimizer backend/tests/optimizer` passed. Equity priority uses tested min-max normalization of one documented EJ-subset indicator, preserves missing values, and maps constant observed values to neutral 0.5._
  - _Requirements: R4_

- [x] **G7. Implement solver interpretation and baseline**
  - Invoke SciPy MILP and map all termination states honestly.
  - Compute selected resources/objective from validated inputs and implement deterministic constrained baseline.
  - Add property-based budget/count invariants, tie behavior, determinism, and baseline comparison tests.
  - _Verified genuine `scipy.optimize.milp` status 0 optimum against exhaustive enumeration: objective 7.0, exhaustive 7.0, selected `('B',)`; no real coordinates are integrated and every test coordinate is labeled `synthetic_test_fixture`._
  - _Requirements: R4, R5_

- [x] **G8. Implement `POST /api/optimize`**
  - Return exact contract fields, assumptions, model-vs-observed caveat, solver metadata, and infeasible behavior.
  - Add API/contract tests and wire routers only through shared composition.
  - _Verified 2026-10-24 in the same exact Python 3.11.10 run: actual TestClient `POST /api/optimize` for 3 events, 25 km, lambda 0.6 returned HTTP 200/optimal, native status 0, gap 0.0, selected Hudson/Reading/Sharon, covered 87 municipalities and EJ-subset population proxy 2,636,354 with objective 1,639,905.9010591828. Zero events returned an optimal empty plan. Parameter-change tests proved each request invoked the solver and produced mathematically different results; condition-specific requests returned structured 409 responses rather than implying an unsupported objective._
  - _Requirements: R4, R5_

- [x] **G9. Build researcher dashboard integration**
  - Use MapLibre with accessible source/derived layers, legends, no-data state, freshness, and limitations.
  - Integrate optimization inputs/results without implying enrollment prediction.
  - Run frontend typecheck/build and critical interaction verification.
  - _Verified 2026-10-24 with Node 22.14.0: `npm run typecheck` passed and Next.js 16.4.3 `npm run build` compiled `/researcher` successfully. A production server smoke request returned the researcher route with its controls. The route loads real `/api/geo` data and each Run action sends current event/radius/equity controls to `/api/optimize`; backend tests verify each changed request invokes a fresh solver run. Clinical conditions remain disabled while the genuine site export is unavailable._
  - _Requirements: R3, R5_

- [ ] **G10. Workstream verification and handoff**
  - Run complete geographic/optimizer pytest suites and frontend checks; record exact commands/results.
  - Reconcile observed source counts and provenance; distinguish fixtures from actual records.
  - Update limitations and Kiro usage with facts only.
  - Commit stable checkpoint and communicate site exchange/API behavior to integration owners.
  - _Requirements: R1–R5_

## Completion gate

Successful solutions must satisfy validated constraints, source completeness/failures must be explicit, and APIs must honor `contracts/api.md`. Reduce geographic breadth or visual polish before compromising provenance, mathematical validity, or honest interpretation.
