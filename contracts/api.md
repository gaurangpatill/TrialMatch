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
| `phase` | string | null | Canonical source phase; `NA` and `NOT_APPLICABLE` filter the canonical `NOT_APPLICABLE` value |
| `age_years` | number | null | `0..125`; matches each available published bound independently and excludes records with neither bound |
| `location` | string | null | Facility, city, state, or country substring; returned locations remain the complete source list |
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
      "source_description": "Official study-purpose text from ClinicalTrials.gov.",
      "brief_summary": "Official study-purpose text from ClinicalTrials.gov.",
      "detailed_description": "Longer official technical description when provided.",
      "plain_language_summary": null,
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

`total_items` is an observed accepted count for the applied local query, never the approximate challenge count. `brief_summary` and `detailed_description` preserve the separate nullable official ClinicalTrials.gov fields. `source_description` is the concise official display fallback (brief summary preferred, then detailed description). `plain_language_summary` is nullable and is served only from a validated cache for the current source hash; search and detail reads never invoke an LLM. Cached summaries are explanatory text, not eligibility evidence, and the official source text/link remains authoritative.

`GET /api/trials/{nct_id}` returns the same summary fields plus eligibility text, contacts, retrieval provenance, and extraction coverage. It may retrieve one official detail record when expansion is missing or explicitly refreshed; it does not trigger paid model calls. Facility arrays preserve all source locations. Consumers must identify Massachusetts facilities from the explicit state field and must not label the worldwide array as Massachusetts-only.

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
      "screening_status": "unresolved",
      "extraction_coverage": {
        "status": "partial",
        "protocol_item_count": 8,
        "accounted_item_count": 6,
        "evaluable_criterion_count": 4,
        "unsupported_protocol_requirement_count": 2,
        "uncovered_protocol_requirement_count": 2,
        "independently_verified": false,
        "verification_method": null,
        "reason": "Eligibility extraction is partial: 2 explicitly enumerated protocol requirements remain unprocessed."
      },
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
- `extraction_coverage.status`: `not_attempted | partial | complete | failed | stale`

`extraction_coverage` is independent of criterion outcomes. It records explicit protocol-item accounting for the current source version; criterion count and provider-declared completeness alone never establish completeness. `potential_match` is allowed only when current-source coverage is declared complete **and separately approved through a persisted independent verification method**, at least one criterion is deterministically evaluable, every evaluated criterion is `met`, and there are no unknown, unsupported, uncovered, or contradictory requirements. A reliable failed inclusion or applicable exclusion still produces `known_mismatch` under incomplete coverage. All other incomplete, unsupported, stale, failed, or unknown cases return `unresolved`.

A result is `known_mismatch` when a known fact fails an inclusion or satisfies an exclusion. Missing facts never produce `met`. Coverage completeness is preliminary protocol accounting, not confirmed eligibility or clinical validation. Overall aggregation rules must remain deterministic and documented in the Clinical Intelligence design.

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

Optimizer ownership. Solves a fixed, persisted Massachusetts EJ-subset outreach scenario with SciPy MILP. Public callers may tune only bounded scenario controls; they cannot submit arbitrary matrices, costs, or candidates.

**Request**

```json
{
  "max_events": 3,
  "coverage_radius_km": 25,
  "equity_weight": 0.6
}
```

Rules:

- `max_events` is an integer from `0..20`.
- `coverage_radius_km` is finite and from `0..200`.
- `equity_weight` is finite and from `0..1`.
- Optional `condition` is accepted only to return an explicit `409`; condition-specific optimization is unsupported because no validated condition-specific demand/access-gap term exists. Condition-filtered `/api/geo` indicators and the optimizer remain independent.
- Requests are limited per client/process. `429` uses the common envelope and includes `Retry-After`. The prototype limiter resets on process restart and is not a distributed quota.

The `200` response includes solver status, selected municipality analytical points, exact covered municipality IDs/counts, modeled EJ-subset population proxy and weighted objective, equal abstract event costs, baseline comparisons, constraint checks, assumptions, limitations, scenario construction, and persisted-source provenance. Municipality representatives are analytical points, not verified outreach venues. Results are modeled outreach coverage, not observed enrollment.

`status`: `optimal | feasible | infeasible | unbounded | solver_error`. A mathematically infeasible request may return `200` with `status: "infeasible"` and no selections when the optimization ran correctly. Invalid inputs use `422`; unavailable persisted data uses `503`. Never label a non-optimal result as optimal.

All geography `409` and `503` failures use the common error envelope. Geography summary provenance distinguishes export input/schema-accepted rows from producer source locations, explicit Massachusetts locations, status/name exclusions, duplicates, and final condition-filtered rows. Legacy count fields remain temporarily for compatibility.

## Contract acceptance

Before integration, each implemented endpoint must have:

1. Pydantic request/response models matching this document.
2. Contract/API tests for success and error envelopes.
3. Stable enum, nullability, and pagination behavior.
4. Source/provenance fields populated from observed data.
5. A frontend build against the implemented contract.
6. Updated examples if an agreed change is made.
