# Limitations and Safety

## Intended use

TrialMatch is a hackathon research-access prototype. It supports exploration and preliminary screening with synthetic patient profiles. It is not medical advice, a diagnostic tool, a medical device, a validated clinical decision-support system, or confirmation of trial eligibility. Study staff and current official records remain authoritative.

## Clinical limitations

- ClinicalTrials.gov data may be incomplete, delayed, changed, or inconsistent across records.
- Recruitment status at a study or location can change after retrieval.
- Natural-language eligibility criteria contain temporal, clinical, and logical nuance that a limited structured vocabulary cannot always encode.
- LLM extraction can be wrong. Structured validation checks shape, not medical truth.
- Unsupported, missing, ambiguous, or contradictory facts must remain `unknown`; they must not be converted into a positive match.
- Contact information may be unavailable. TrialMatch must not invent it.
- Match ordering is not a probability of eligibility or recommendation to enroll.

## Data and privacy limitations

Only synthetic patient profiles are allowed in development and demonstrations. The system is not designed for PHI, patient accounts, consent workflows, retention controls, or regulated clinical operations. MassGIS Environmental Justice fields are aggregate community statistics and must not be interpreted as patient-level attributes.

## Geographic limitations

- Aggregate block-group indicators do not describe every resident and are subject to source definitions and vintage.
- Municipality aggregation can hide within-area variation.
- Geocoding, location resolution, distance assumptions, and missing trial facilities affect access estimates.
- Map visualization does not establish causation or actual accessibility.

## Optimizer limitations

The SciPy MILP selects locations according to modeled inputs, constraints, and objective weights. Its result is modeled outreach coverage—not observed enrollment, causal impact, equity certification, or a guarantee of feasibility in practice. Every result must expose assumptions, budget/resource constraints, objective value, solver status, and baseline comparison.

## Prototype and operational limitations

Clinical ingestion, local search, deterministic source-structured age/sex screening, matching APIs, and the synthetic Patient Portal are implemented and verified on the clinical feature branch. The checked-in manifest records a complete 3,145-study source snapshot acquired on October 24, 2026, but generated SQLite/cache data is intentionally not committed and must be reproduced during deployment. Only 20 studies received expanded detail retrieval in that run.

The schema-guided LLM extraction adapter and cache boundary are implemented and tested with controlled providers, but no live provider was configured for the verified run. Therefore no criterion may be represented as LLM-extracted until a named provider/model is configured and a successful bounded extraction is recorded. Source-structured criteria are labeled separately.

MassGIS analysis, optimization, and their dashboard remain independently owned and are not validated by the clinical workstream. SQLite and a single-process modular monolith are appropriate for the prototype but not automatically appropriate for multi-instance production use. Security, accessibility, load, disaster recovery, legal, clinical, and privacy reviews remain necessary before any real-world use.
