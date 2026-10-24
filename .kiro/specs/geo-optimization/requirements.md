# Geographic Intelligence and Optimization Requirements

## Scope

Developer B implements this spec on `feature/geo-optimization`, not `main`. The workstream owns MassGIS ingestion, aggregate geographic analysis, trial-site access indicators, SciPy MILP outreach optimization, researcher dashboard behavior, APIs, and tests.

## Requirements

### R1 — Verifiable MassGIS ingestion

**User story:** As a reviewer, I want official aggregate Environmental Justice records acquired completely so that geographic claims are reproducible.

Acceptance criteria:

1. THE SYSTEM SHALL query the official MassGIS EJ2020 service with `EJ='Yes'` and preserve required source fields.
2. WHEN more records exist than the service page size, THE SYSTEM SHALL paginate with `resultOffset`/`resultRecordCount`, honor transfer-limit evidence, and guard against repeated pages.
3. THE SYSTEM SHALL inspect source count/service metadata where available and record actual raw/accepted counts rather than the approximate challenge count.
4. THE SYSTEM SHALL preserve a source object/block-group identifier when available and SHALL detect duplicate identifiers.
5. THE SYSTEM SHALL record exact source query, UTC acquisition time, schema results, missing values, transformations, filters/exclusions, checksum where applicable, and partial failures.
6. IF source access fails, THEN THE SYSTEM SHALL document a retryable method/failure and SHALL NOT substitute fabricated observations.

### R2 — Aggregate geographic model

Acceptance criteria:

1. THE SYSTEM SHALL normalize `MUNICIPALITY`, `TOTAL_POP`, `PCT_MINORITY`, `LIMENGHHPCT`, `BG_MHHI`, `EJ`, and `EJ_CRIT_DESC` with explicit units/null semantics.
2. THE SYSTEM SHALL represent these as aggregate community attributes and SHALL NOT infer patient-level characteristics.
3. Any municipality aggregation SHALL document formulas, weighting, missing-value handling, and denominator choices.
4. Any geometry SHALL identify its official source and acquisition; geometry SHALL remain null when only the provided non-geometry query was used.

### R3 — Trial-site and access analysis

Acceptance criteria:

1. THE SYSTEM SHALL consume trial-site data through an agreed shared contract/export, not by importing clinical internals.
2. Trial-site deduplication, location resolution, missing coordinates, and Massachusetts filtering SHALL be documented and tested.
3. Any access score SHALL define components, direction, scale, assumptions, and missing-data behavior and SHALL distinguish raw from derived fields.
4. `GET /api/geo` SHALL conform to `contracts/api.md` and include observed source freshness.

### R4 — Honest constrained optimization

**User story:** As a researcher, I want outreach locations selected under explicit constraints so that a limited-resource plan can be compared with a simple baseline.

Acceptance criteria:

1. THE SYSTEM SHALL formulate location-selection decision variables, objective terms, budget/resource constraints, and units explicitly using SciPy MILP.
2. THE SYSTEM SHALL validate finite non-negative costs/budget, unique known candidate IDs, positive location limits, supported constraints, and objective weights.
3. THE SYSTEM SHALL report solver status accurately and SHALL never call a feasible/non-optimal, infeasible, unbounded, or failed result optimal.
4. THE SYSTEM SHALL expose selected locations, total cost, objective value, modeled coverage, assumptions, solver details, and deterministic baseline comparison.
5. Outputs SHALL be labeled modeled outreach coverage, not enrollment predictions or causal outcomes.
6. Repeated runs with the same deterministic inputs/configuration SHALL produce equivalent selections or document tie behavior.

### R5 — Researcher experience and verification

Acceptance criteria:

1. `POST /api/optimize` SHALL conform to the shared contract, including infeasible and invalid-input behavior.
2. The researcher dashboard SHALL use MapLibre for source/derived geographic layers and SHALL display definitions, freshness, legends, and limitations.
3. Tests SHALL cover pagination, duplicate IDs, source-schema/missing values, aggregation math, trial-site handling, constraint satisfaction, infeasibility, baseline comparison, and deterministic behavior.
4. Property-based tests SHALL validate useful invariants such as selected cost not exceeding budget and selected count not exceeding limits for successful results.
5. No source count, access metric, optimization outcome, map layer, or test SHALL be represented as operational until executed and verified.

## Out of scope

Patient-level inference, observed enrollment prediction, causal impact, guaranteed real-world accessibility, modifications to clinical-owned modules, distributed optimization infrastructure, and unsupported geometry/source claims.
