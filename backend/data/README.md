# Local data workspace

`manifest.json` is the only source-data artifact tracked by default. Create `raw/`, `derived/`, and `cache/` locally as ingestion requires; their contents and SQLite files are ignored because they may be large, generated, stale, or sensitive in aggregate.

- `raw/`: immutable source responses or supplied ZIP snapshots.
- `derived/`: reproducible normalized exports.
- `cache/`: retrievable API and structured extraction cache.

Every real acquisition must update provenance metadata based on observed results, not challenge estimates. See `../../docs/data-provenance.md`.
