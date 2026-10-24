# Geographic Intelligence and Optimization Technical Design

## Design goals

Complete source acquisition, transparent aggregate transformations, mathematically valid constraints, and honest interpretation take priority over map polish. Implement only on `feature/geo-optimization`.

## Components

```text
MassGISClient ─► GeographyIngestionService ─► GeographyRepository (SQLite)
      │                    │
      └── raw cache        └── provenance/run report

Agreed trial-site exchange ─► SiteNormalizer
MassGIS + sites ─► AccessAnalysis ─► Geo API / MapLibre-ready GeoJSON
                              │
                              ▼
                      OptimizationInputBuilder
                              │
                              ▼
                    SciPyMilpOptimizer ─► BaselineComparator
                              │
                              ▼
                         Optimize API
```

Network clients, source models, normalized domain models, repositories, pure calculations, optimization formulation, and API routers remain separable. Geography may expose stable interfaces to optimizer; neither imports clinical implementation internals.

## MassGIS ingestion

Use the exact official ArcGIS query semantics. Inspect service metadata and/or `returnCountOnly=true`. Request pages using `resultOffset` and `resultRecordCount` with a deterministic order/object identifier if supported. Track seen identifiers/page fingerprints, `exceededTransferLimit`, page sizes, and count reconciliation. A short page alone is not proof of completion when the service says its transfer limit was exceeded.

Validate the ArcGIS envelope and feature attributes before normalization. Record source URL/parameters, timestamps, checksums where snapshots are stored, source/accepted counts, duplicates, missing fields, exclusions, and partial failures.

## Geographic models and derivations

Preserve required source names in raw models and use documented snake_case normalized fields. Percent values declare whether units are `0..100` or fractions. Income/currency records units and vintage where source metadata provides it. Aggregate only with explicit rules: sums for compatible population counts; population-weighted rates only with valid denominators; never silently treat missing as zero.

Map output is GeoJSON. The supplied query has `returnGeometry=false`; polygon/point geometry remains null until separately acquired from an official documented source. Aggregate EJ fields are not patient attributes.

Trial-site exchange uses stable NCT/facility/location fields from the contract or a coordinated export. Resolve/deduplicate sites with transparent keys and preserve unresolved locations instead of inventing coordinates.

Any access score is a versioned derived model with component definitions, scaling, direction, weights, and missingness. Keep raw inputs alongside derived output and test monotonicity where expected.

## Optimization formulation

Start with binary decision variable `x_i` for each candidate outreach location. Define all objective coefficients from versioned modeled access/coverage inputs. Minimum constraints:

- `sum(cost_i * x_i) <= budget`;
- `sum(x_i) <= max_locations`;
- integrality and `0 <= x_i <= 1`;
- only explicitly supported policy constraints.

Build arrays/matrices separately from solver invocation so units and index-to-location mappings can be tested. Validate finite numbers and reject unknown IDs/constraints. Run `scipy.optimize.milp`; map native termination states without overstating optimality. For infeasibility return no selections and actionable assumptions/constraint context.

Define a deterministic baseline such as highest modeled population coverage per documented greedy rule, respecting identical budget/location constraints. Specify tie-breaking by stable location ID. Compare the same objective units.

## API and dashboard

`GET /api/geo` returns source/derived properties and optional official geometry under `contracts/api.md`. `POST /api/optimize` returns selected IDs, exact total cost, objective, modeled coverage, baseline, solver metadata, assumptions, and timestamp.

The frontend owns MapLibre presentation: accessible legends, source/freshness labels, raw-vs-derived explanations, null/no-data treatment, and optimizer assumptions. It must not imply that EJ status describes individuals or that modeled coverage predicts enrollment.

## Failure modes

- Partial/repeated ArcGIS pages: mark run incomplete and do not publish as complete.
- Missing identifier: quarantine or create only a documented non-source surrogate while retaining the problem.
- Missing denominator/rate: preserve null and exclude only with recorded reason.
- Missing trial coordinate: retain unresolved site and exclude from spatial operation with counts.
- Invalid optimizer input: reject before solver.
- Infeasible/unbounded/failed solver: report accurate status, no invented plan.
- Ties: deterministic documented tie-break or equivalent-solution note.

## Verification strategy

Use mocked ArcGIS pages for pagination/transfer-limit/repeated-page cases and source-shape failures. Unit-test weighted aggregation, missingness, site deduplication, access calculations, matrix construction, baseline, and status mapping. Add small known MILP fixtures with manually checkable optima and infeasible cases. Use Hypothesis for feasible-result budget/count constraints, deterministic transformations, and expected monotonic properties.

Verify an actual source acquisition only when network access succeeds; distinguish it from fixtures. Run frontend type/build checks for dashboard integration and contract tests for both endpoints.
