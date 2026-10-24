# Clinical-to-Geographic Site Export

`ma_trial_sites.json` is a committed, reproducible handoff generated from actual ClinicalTrials.gov API v2 individual study records. It does not depend on access to the ignored local SQLite database once cloned.

## Geographic integration

Use the top-level `geography_records` array. Each item matches the geographic branch's strict `TrialSite` model:

- `resolution_status` is `source_coordinates` or `unresolved`.
- Resolved records include `coordinate_source` and `coordinate_source_reference`.
- `overall_status` is the study-level status expected by the current geographic adapter.
- Every exported location was also filtered to source site-level status `RECRUITING` before mapping.

The top-level `records` array is one-to-one and additionally includes:

- `coordinate_status`: `verified` when a valid source coordinate pair exists, otherwise `unresolved`.
- `facility_recruitment_status`: the source site-level `RECRUITING` value used by export filtering.

No geocoding or coordinate inference is performed. In this schema, `verified` means structurally valid and source-provided—not independently confirmed facility-level precision.

## Reproduction

First reproduce/expand the ignored local clinical snapshot:

```bash
python -m backend.app.clinical.cli ingest \
  --page-size 1000 \
  --detail-limit 100 \
  --detail-condition cancer \
  --detail-delay-seconds 0.25 \
  --update-manifest backend/data/manifest.json
```

Then export:

```bash
python -m backend.app.clinical.cli export-sites \
  --output backend/data/exports/ma_trial_sites.json \
  --cohort-description "100 cancer-related recruiting studies selected deterministically by NCT ID from title/condition matches; expanded from the 3,145-study Massachusetts recruiting snapshot acquired 2026-10-24"
```

The artifact metadata is authoritative for its generation timestamp, cohort, counts, exclusions, coordinate resolution, deduplication rule, and limitations. The committed cohort is partial and cancer-focused; it must not be presented as complete Massachusetts site coverage.
