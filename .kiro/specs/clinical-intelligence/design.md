# Clinical Intelligence Technical Design

## Design goals

Correct ingestion, explicit uncertainty, deterministic evaluation, and source traceability take priority over study breadth or visual polish. Implement this design only on `feature/clinical-intelligence`.

## Components

```text
ClinicalTrialsClient ─► IngestionService ─► StudyRepository (SQLite)
       │                       │
       └── raw/detail cache    └── provenance/run report

StudyRecord ─► ExtractionService ─► Pydantic validation ─► CriteriaRepository
                    │
              LLMProvider protocol
              (disabled/provider implementation)

SyntheticPatient + StructuredCriteria
                    │
                    ▼
          DeterministicEvaluator
                    │
                    ▼
             MatchingService ─► clinical FastAPI router
```

Suggested internal packages: `clients`, `ingestion`, `models`, `repositories`, `extraction`, `evaluation`, `matching`, and `router`. Keep network, persistence, provider, and pure evaluator concerns separable.

## Ingestion design

Use an `httpx` client with configured timeout, bounded exponential retry for transient status/network errors, and no retry for structural/client errors. Enumerate list pages using `nextPageToken`; track seen tokens and NCT IDs. Fetch selected detail records through `/studies/{NCTId}` and atomically cache successful JSON with retrieval metadata.

An ingestion run record contains source query, start/end UTC, completion/partial status, page count, raw/accepted counts, duplicate IDs, missing-field counts, exclusions, failures, and source/cache checksums where practical. ZIP and API adapters feed the same validator/normalizer.

SQLite tables should separate source snapshots/run metadata, normalized studies, and extraction cache. Repository interfaces prevent SQLite details from entering evaluation logic.

## Domain models

A normalized `Study` preserves source fields and original eligibility text. A `StructuredCriterion` includes:

- stable criterion ID and NCT ID;
- `classification`: inclusion/exclusion;
- exact `original_text` and optional source section/position;
- supported attribute enum;
- operator enum;
- typed comparison value/unit;
- optional lower/upper bounds and inclusivity;
- optional temporal window and unit;
- supported compound children/operator when representable;
- extraction metadata (schema version, provider/model, timestamp, uncertainty).

Start with a narrow vocabulary: age, asserted condition presence/absence, sex restriction where protocol-compatible, selected procedure/medication facts with explicit temporal data, numeric ranges, boolean logic `all`/`any` where each child is independently supported. Preserve unsupported source text as an unevaluable criterion.

A `SyntheticPatient` requires `synthetic=true`. Fact presence and fact absence must be distinguishable; an omitted list item is not proof of absence.

## Extraction boundary

The provider receives only necessary public protocol text and an explicit schema/vocabulary. Parse response into Pydantic with forbidden unknown fields, enum validation, logical-shape checks, and source-evidence checks. Reject the whole malformed extraction or quarantine invalid items according to a documented policy; never silently coerce clinical meaning.

Cache keys include NCT ID, source content hash/version, extraction schema version, prompt version, provider/model identity. Provider failure returns a typed unavailable result and never delegates eligibility judgment to free text.

## Deterministic evaluator

Implement evaluator functions as pure code. Criterion polarity is separate from predicate truth:

- Inclusion predicate true → `met`; false → `not_met`; insufficient → `unknown`.
- Exclusion predicate true (the exclusion applies) → `not_met`; false with explicit contrary fact → `met`; insufficient → `unknown`.

Compound evaluation uses three-valued logic. For `all`, any false determines false, all true determines true, otherwise unknown. For `any`, any true determines true, all false determines false, otherwise unknown. Apply classification polarity once to the compound predicate, avoiding double negation.

Age/range operations define boundary inclusivity in structured data. Temporal operations require a reference date and dated fact; otherwise unknown. Unsupported operators/attributes always return unknown with a reason. Detect contradictory structured criteria and expose a warning.

Overall trial status is gated by an independently persisted current-source extraction coverage record:

- `known_mismatch` if any reliable current-source criterion is `not_met`, even when coverage is incomplete;
- `potential_match` only when explicit protocol-item accounting is declared `complete`, a separate persisted independent coverage approval is current, at least one criterion is evaluable, every current criterion is `met`, and no criterion, gap, unsupported item, or contradiction is unresolved;
- `unresolved` for not-attempted, partial, failed, stale, unsupported, missing-patient-fact, contradictory, or zero-evaluable-criterion cases.

Source-structured age/sex rules do not establish full protocol coverage. Coverage metadata must use deterministic source-item identities and enumerate accounted criteria and verbatim uncovered source items. Obvious multi-clause items require compound representation, but provider declarations still cannot self-verify semantic completeness: a separate persisted `manual_protocol_review` or test-only `deterministic_test_fixture` approval is required. Successful provider execution or rule count alone never proves completeness. No score, probability, or confirmed eligibility is inferred.

## API behavior

Expose a clinical router that conforms to `contracts/api.md`. Search reads normalized local records and never causes bulk extraction. Match validates synthetic profiles, evaluates selected/candidate studies using cached criteria, and emits evidence, status, unresolved requirements, missing questions, sources, and the fixed caution disclaimer.

## Failure modes

- Pagination/source failure: persist partial run state; do not label complete.
- Duplicate NCT ID: compare source version/content and apply documented deterministic resolution or reject conflict.
- Missing source field: retain missingness and report; only reject required identity failures.
- Invalid model output: reject/quarantine and use no rules from it.
- Provider unavailable: use valid cache; otherwise return typed unavailable/unresolved state.
- Contradictory criteria: retain each result and expose conflict warning.

## Verification strategy

Unit-test pure normalization/evaluation and three-valued logic. Use fixture HTTP transports for pagination, retry, duplicates, and missing fields. Add Pydantic rejection tests and provider/cache fallback tests. API tests validate exact contract shapes. Use Hypothesis for meaningful invariants: identical inputs are deterministic; adding no fact cannot turn unknown into met; age comparisons honor declared boundaries; resource-independent criterion order does not alter aggregate status.

Acceptance is based on executed tests and observed source reports, never fixture counts represented as real ingestion.
