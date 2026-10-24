# TrialMatch Shared API Contract

**Contract version:** 0.1.0 scaffold
**Base path:** `/api`
**Media type:** `application/json`

This document is the coordination boundary between backend workstreams and the frontend. Examples are illustrative contracts, not evidence that endpoints other than health are implemented. Breaking changes require agreement from both workstream owners before frontend integration.

## Conventions

- JSON keys use `snake_case`.
- Timestamps are ISO 8601 UTC strings such as `2026-10-24T17:30:00Z`.
- Unknown optional values are `null` or omitted only where explicitly allowed; clinical criterion status uses the explicit `unknown` enum.
- Resource identifiers preserve official source identifiers.
- Lists return deterministic ordering and pagination metadata.
- `source_url` links to the authoritative record.
- Patient profiles used by this prototype must include `synthetic: true`.
- Clinical results are preliminary and never probabilities or confirmed eligibility.

## Common errors

All non-2xx responses use:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed.",
    "details": [{"field": "page_size", "reason": "must be between 1 and 100"}],
    "retryable": false,
    "request_id": "01JAZ..."
  }
}
```

Expected statuses: `400` invalid business input, `404` unknown resource, `422` request schema error, `429` rate limit, `502` upstream failure, `503` unavailable dependency, `500` unexpected internal error. Error details must not expose secrets or private data.

---

## `GET /api/health`

Shared ownership. Reports process readiness, not feature completeness or external-source freshness.

**200 response**

```json
{
  "status": "ok",
  "service": "trialmatch-api",
  "version": "0.1.0"
}
```

Schema:

| Field | Type | Required | Rules |
|---|---|---:|---|
| `status` | `"ok"` | yes | Process is responsive |
| `service` | string | yes | `trialmatch-api` |
| `version` | string | yes | Application version |

---

## `GET /api/trials`

Clinical Intelligence ownership. Searches normalized recruiting studies; it must not trigger synchronous bulk LLM extraction.

Query parameters:

| Name | Type | Default | Rules |
|---|---|---:|---|
| `query` | string | null | Title/condition text; trimmed, max 200 chars |
| `condition` | string | null | Exact or documented normalized condition filter |
| `phase` | string | null | Source phase value |
| `page` | integer | 1 | `>= 1` |
| `page_size` | integer | 20 | `1..100` |

**200 response**

```json
{
  "items": [
    {
      "nct_id": "NCT01234567",
      "title": "Example Study",
      "overall_status": "RECRUITING",
      "conditions": ["Example condition"],
      "phases": ["PHASE2"],
      "minimum_age": "18 Years",
      "maximum_age": null,
      "sex": "ALL",
      "locations": [
        {
          "facility": "Example Research Center",
          "city": "Boston",
          "state": "Massachusetts",
          "postal_code": null,
          "country": "United States",
          "latitude": null,
          "longitude": null
        }
      ],
      "source_url": "https://clinicaltrials.gov/study/NCT01234567",
      "retrieved_at": "2026-10-24T17:00:00Z"
    }
  ],
  "pagination": {"page": 1, "page_size": 20, "total_items": 1, "total_pages": 1},
  "data_freshness": {"retrieved_at": "2026-10-24T17:00:00Z", "source": "ClinicalTrials.gov"}
}
```

`total_items` is an observed accepted count for the applied local query, never the approximate challenge count.

---

## `POST /api/match`

Clinical Intelligence ownership. Evaluates a synthetic profile against cached structured criteria with deterministic three-state reasoning.

**Request**

```json
{
  "patient": {
    "profile_id": "synthetic-adult-001",
    "synthetic": true,
    "age_years": 42,
    "sex": "female",
    "conditions": ["example condition"],
    "medications": [],
    "procedures": [],
    "absent_conditions": [],
    "absent_medications": [],
    "absent_procedures": [],
    "condition_days_ago": {},
    "medication_days_ago": {},
    "procedure_days_ago": {},
    "laboratory_values": {},
    "attributes": {}
  },
  "trial_ids": ["NCT01234567"],
  "limit": 20
}
```

Request rules:

- `synthetic` must equal `true`; otherwise reject with `400`.
- `age_years` is decimal or null, range `0..125`.
- Clinical fact lists contain explicitly asserted facts only; absence from a positive list is not negation.
- `absent_conditions`, `absent_medications`, and `absent_procedures` contain only facts explicitly known to be absent; a fact present in both positive and absent lists is rejected.
- The three `*_days_ago` maps contain finite non-negative elapsed-day values for explicitly present facts and support bounded temporal predicates.
- `laboratory_values` contains bare numeric values under this contract. Unit-sensitive laboratory criteria therefore remain `unknown` until a coordinated unit-bearing fact schema is introduced.
- `trial_ids` is optional, unique, maximum 100. Unknown requested IDs return `404`. If omitted, documented search candidates are used.
- `limit` defaults to 20 and is `1..100`.
- Unsupported extra clinical attributes may be preserved under `attributes` but evaluate as `unknown` unless explicitly supported.

**200 response**

```json
{
  "profile_id": "synthetic-adult-001",
  "results": [
    {
      "nct_id": "NCT01234567",
      "title": "Example Study",
      "screening_status": "potential_match",
      "criteria": [
        {
          "criterion_id": "NCT01234567-inc-001",
          "classification": "inclusion",
          "status": "met",
          "original_text": "Participants must be 18 years or older.",
          "explanation": "The synthetic profile age is 42 years; the criterion minimum is 18 years.",
          "source_url": "https://clinicaltrials.gov/study/NCT01234567",
          "extraction_uncertainty": null
        },
        {
          "criterion_id": "NCT01234567-exc-002",
          "classification": "exclusion",
          "status": "unknown",
          "original_text": "No major surgery within 30 days.",
          "explanation": "The profile does not provide sufficient dated procedure information.",
          "source_url": "https://clinicaltrials.gov/study/NCT01234567",
          "extraction_uncertainty": "Temporal relationship requires confirmation."
        }
      ],
      "known_mismatches": [],
      "unresolved_requirements": ["No major surgery within 30 days."],
      "missing_questions": ["Has the person had major surgery in the last 30 days?"],
      "source_url": "https://clinicaltrials.gov/study/NCT01234567"
    }
  ],
  "disclaimer": "Preliminary screening only. Study staff must confirm eligibility.",
  "generated_at": "2026-10-24T17:30:00Z"
}
```

Enums:

- `criterion.status`: `met | not_met | unknown`
- `criterion.classification`: `inclusion | exclusion`
- `screening_status`: `potential_match | known_mismatch | unresolved`

A result is `known_mismatch` when a known fact fails an inclusion or satisfies an exclusion. Missing facts never produce `met`. Overall aggregation rules must be deterministic and documented in the Clinical Intelligence design.

---

## `GET /api/geo`

Geographic Intelligence ownership. Returns aggregate community and trial-site information suitable for a MapLibre layer.

Query parameters:

| Name | Type | Default | Rules |
|---|---|---:|---|
| `municipality` | string | null | Optional municipality filter |
| `ej_only` | boolean | true | Include only source-flagged EJ areas when true |
| `include_geometry` | boolean | true | Include GeoJSON geometry if available |

**200 response**

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "source-block-group-id",
      "geometry": null,
      "properties": {
        "municipality": "Boston",
        "total_population": 1200,
        "percent_minority": 55.2,
        "limited_english_household_percent": 12.4,
        "block_group_median_household_income": 52000,
        "ej": "Yes",
        "ej_criteria_description": "Source description",
        "trial_site_count": 3,
        "access_score": null
      }
    }
  ],
  "summary": {
    "observed_feature_count": 1,
    "source": "MassGIS EJ2020",
    "retrieved_at": "2026-10-24T17:10:00Z"
  }
}
```

`geometry` may be null because the required starter query sets `returnGeometry=false`; the service/geometry acquisition method must be documented before map polygons are claimed. `access_score` must remain null until a defined and validated derivation exists.

---

## `POST /api/optimize`

Optimizer ownership. Solves a documented outreach location selection model with SciPy MILP and compares it to a baseline.

**Request**

```json
{
  "candidate_location_ids": ["BOSTON", "WORCESTER", "SPRINGFIELD"],
  "budget": 100000,
  "max_locations": 2,
  "location_costs": {
    "BOSTON": 60000,
    "WORCESTER": 40000,
    "SPRINGFIELD": 35000
  },
  "objective_weights": {
    "modeled_population_coverage": 1.0,
    "environmental_justice_access": 1.0
  },
  "constraints": []
}
```

Rules: IDs must be unique and known; costs and budget are finite/non-negative; `max_locations` is a positive integer no greater than candidate count; objective terms and units must be documented; unsupported constraints are rejected rather than ignored.

**200 response**

```json
{
  "run_id": "01JAZ...",
  "status": "optimal",
  "selected_location_ids": ["WORCESTER", "SPRINGFIELD"],
  "total_cost": 75000,
  "objective_value": 1234.5,
  "modeled_coverage": {
    "population": 120000,
    "environmental_justice_block_groups": 18
  },
  "baseline": {
    "method": "highest_modeled_population_first",
    "selected_location_ids": ["BOSTON", "WORCESTER"],
    "objective_value": 1100.0
  },
  "solver": {
    "name": "scipy.optimize.milp",
    "termination_message": "Optimization terminated successfully.",
    "mip_gap": 0.0
  },
  "assumptions": ["Coverage values are modeled inputs, not observed enrollment."],
  "generated_at": "2026-10-24T17:45:00Z"
}
```

`status`: `optimal | feasible | infeasible | unbounded | solver_error`. A mathematically infeasible request may return `200` with `status: "infeasible"` and no selections when the optimization ran correctly; invalid inputs use `400/422`. Never label a non-optimal result as optimal.

## Contract acceptance

Before integration, each implemented endpoint must have:

1. Pydantic request/response models matching this document.
2. Contract/API tests for success and error envelopes.
3. Stable enum, nullability, and pagination behavior.
4. Source/provenance fields populated from observed data.
5. A frontend build against the implemented contract.
6. Updated examples if an agreed change is made.
