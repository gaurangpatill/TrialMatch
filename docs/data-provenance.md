# Data Provenance and Validation

The tracked machine-readable source registry is `backend/data/manifest.json`. Raw downloads, derived exports, caches, and SQLite files are local/generated and ignored by Git.

## ClinicalTrials.gov recruiting Massachusetts studies

- **Authority:** U.S. National Library of Medicine, ClinicalTrials.gov API v2
- **Challenge description:** approximately 3,131 recruiting studies with Massachusetts sites; this is an expectation, not a verified count.
- **Starter/API query:** `https://clinicaltrials.gov/api/v2/studies?query.locn=Massachusetts&filter.overallStatus=RECRUITING&pageSize=20&fields=NCTId,BriefTitle,OverallStatus,Condition,Phase`
- **Detailed record pattern:** `https://clinicaltrials.gov/api/v2/studies/{NCTId}`
- **Owner:** Clinical Intelligence

The starter query returns at most 20 records. Complete API ingestion must consume each `nextPageToken`, submit it as `pageToken`, stop only when no next token remains, and guard against repeated tokens. A challenge ZIP may be used if available, but its filename, checksum, acquisition timestamp, license/terms, schema, and observed count must be recorded.

Detailed records should preserve NCT ID, title, status, conditions, phase, eligibility text, minimum/maximum age, sex restrictions, parsed inclusion/exclusion source text, facilities/locations, contacts when present, source URL, and retrieval timestamp. Unavailable fields remain null/empty according to the normalized schema; they are never inferred.

### Verified clinical acquisition — 2026-10-24

The feature-branch ingestion command completed at `2026-10-24T18:45:18.786215Z` using the effective query `https://clinicaltrials.gov/api/v2/studies?query.locn=Massachusetts&filter.overallStatus=RECRUITING&pageSize=1000&fields=NCTId%2CBriefTitle%2COverallStatus%2CCondition%2CPhase&format=json`. It consumed four token-paginated pages and observed 3,145 records: 3,145 accepted, zero duplicate NCT identifiers, and zero schema exclusions. A deterministic cohort of 100 cancer-related title/condition matches, ordered by NCT ID, received individual detail retrieval; all 100 completed, using validated cache entries where available. The manifest records observed missing-field totals.

An earlier Phase 1 attempt completed the list but retrieved only 19 of 20 details because one request remained rate-limited with HTTP 429 after bounded retries. That attempt was correctly marked partial; later retries completed. Counts describe their acquisition timestamps and can change with ClinicalTrials.gov. No raw snapshot checksum is claimed because the generated SQLite/API caches are ignored rather than committed.

### Massachusetts recruiting-site export

`backend/data/exports/ma_trial_sites.json` was generated at `2026-10-24T18:45:22.224605Z` from the 100-study expanded cohort. It includes only source locations explicitly labeled Massachusetts with site-level status `RECRUITING`: 149 NCT/facility records across 86 studies and 72 normalized facility/location tuples. Forty-six Massachusetts locations with inactive or unknown site status were excluded; no included record lacked a facility name. All 149 exported records carried valid source `geoPoint` pairs, so this cohort has zero unresolved coordinates. TrialMatch did not independently geocode or confirm facility-level coordinate precision.

The primary `records` array includes `coordinate_status` and site status. The one-to-one `geography_records` array removes those extra fields and matches the geographic branch's strict `TrialSite` schema, including `resolution_status`, `coordinate_source`, and `coordinate_source_reference`. Export metadata records source scope, cohort selection, counts, deduplication, freshness, and limitations. This is partial cancer-focused coverage, not a complete Massachusetts trial-site census.

## MassGIS Environmental Justice block groups

- **Authority:** Massachusetts Bureau of Geographic Information (MassGIS), EJ2020 ArcGIS MapServer
- **Challenge description:** approximately 2,604 block groups where `EJ='Yes'`; this is an expectation, not a verified count.
- **Query:** `https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/EJ2020/MapServer/0/query?where=EJ%3D%27Yes%27&outFields=MUNICIPALITY,TOTAL_POP,PCT_MINORITY,LIMENGHHPCT,BG_MHHI,EJ,EJ_CRIT_DESC&returnGeometry=false&resultRecordCount=100&f=json`
- **Owner:** Geographic Intelligence

The query caps a page at 100 records. Complete ingestion must first inspect service metadata and/or a `returnCountOnly=true` query, then request stable pages using `resultOffset` and `resultRecordCount` while honoring the service transfer limit. Continue until the expected count is reached or a page is empty and `exceededTransferLimit` is false. Detect repeated pages and preserve a stable source object identifier when the service exposes one. The required normalized fields are `MUNICIPALITY`, `TOTAL_POP`, `PCT_MINORITY`, `LIMENGHHPCT`, `BG_MHHI`, `EJ`, and `EJ_CRIT_DESC`.

This dataset contains aggregate community attributes, not patient-level information.

## Required acquisition record

Every ingestion run must record:

- exact source URL/query and source owner;
- UTC acquisition start/end timestamps and software version/commit;
- raw artifact path and SHA-256 checksum when a file/snapshot is stored;
- source schema and schema-validation failures;
- requested filters and pagination completion evidence;
- observed raw and accepted record counts;
- duplicate source identifiers and handling;
- per-field missing/unresolved values;
- raw-to-normalized transforms;
- filtering/exclusion reasons and counts;
- warnings, retries, partial failures, and freshness.

Approximate challenge counts must never be copied into `observed_record_count`. Acquisition date/count fields stay null until successful retrieval and validation.

## Raw and derived separation

Recommended local layout:

```text
backend/data/
├── manifest.json        # tracked source definitions and latest verified metadata
├── raw/                 # immutable source responses/ZIPs; ignored
├── derived/             # reproducible normalized exports; ignored
└── cache/               # retrievable API/LLM cache; ignored
```

Synthetic demonstration profiles must be labeled `synthetic: true`, stored separately from source datasets, and never represented as observations from ClinicalTrials.gov or MassGIS.

## Failure policy

If access fails, retain the intended official source and implement/document a retryable ingestion path. Record the error and partial state. Do not silently substitute fabricated records. Any curated fixture must be explicitly labeled as a test fixture and traceable to its origin or documented synthetic construction.
