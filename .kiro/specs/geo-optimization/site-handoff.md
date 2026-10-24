# Clinical Trial-Site Handoff Required for G4

This handoff is non-blocking for MassGIS ingestion and municipality aggregation. Geographic access analysis must consume a coordinated public export or API response and must not import `backend/app/clinical/` internals.

## Required fields

- `nct_id`: official ClinicalTrials.gov identifier
- `facility_source_id`: stable source identifier when available; otherwise `null`
- `facility_name`
- `city`, `state`, `postal_code`, `country`
- `latitude`, `longitude`: nullable
- `coordinate_source`: nullable source/provenance label
- `resolution_status`: e.g. `source_coordinates`, `verified_geocode`, `unresolved`
- `conditions`: normalized or source condition labels used for filtering
- `overall_status`
- `source_url`
- `retrieved_at`: ISO 8601 UTC

## Semantics to coordinate

1. Include only facilities explicitly located in Massachusetts for Massachusetts access calculations; a study-level Massachusetts match does not make every facility a Massachusetts site.
2. Preserve unresolved facilities with null coordinates. Geography will report and exclude them only from distance calculations; it will not invent coordinates.
3. Agree on a deduplication key. Preferred order is stable facility source ID; otherwise use a documented normalized tuple of NCT ID, facility name, city, state, postal code, and coordinates.
4. Preserve one-to-many study/facility relationships so geography can count distinct recruiting studies without double-counting duplicate facility records.
5. Define condition matching and freshness behavior before condition-specific optimization is exposed.

## Integration request

The clinical owner should provide either a versioned JSON/SQLite export or a documented backend interface with the fields above. Any addition to `contracts/api.md`, `backend/app/main.py`, shared storage, or frontend types requires both owners' agreement before implementation.
