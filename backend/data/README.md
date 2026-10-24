# TrialMatch data boundaries

Tracked public artifacts:

- `manifest.json`: source definitions and observed acquisition evidence.
- `exports/ma_trial_sites.json`: versioned ClinicalTrials.gov-to-geography handoff for the documented partial expanded cohort.
- `../app/geography/data/municipality_ej_subset_aggregates.json`: validated 187-municipality aggregate snapshot derived from 2,604 EJ-flagged block groups.
- `../app/geography/data/municipality_ej_representative_points.json`: 187 analytical representative points. They are not verified outreach venues.

Ignored runtime artifacts:

- `raw/`: immutable source responses or supplied ZIP snapshots.
- `derived/`: local reproducible normalized outputs.
- `cache/`: retrievable API and structured LLM caches.
- `trialmatch.sqlite3` and SQLite WAL/SHM files: normalized clinical runtime data.

A fresh deployment does **not** contain the clinical SQLite database. Attach a persistent Render disk at `/var/data` and run the finite ClinicalTrials.gov ingestion command in [`../../docs/deployment.md`](../../docs/deployment.md) before release acceptance. Require a complete pagination report and nonzero search result; `/api/health` alone is not data readiness. Live-source re-ingestion is reproducible logic but not byte-identical restoration because no checksum-pinned clinical source snapshot is committed.

Never commit databases, raw caches, secrets, or patient data. Every real acquisition must update provenance from observed results, not challenge estimates. See [`../../docs/data-provenance.md`](../../docs/data-provenance.md).
