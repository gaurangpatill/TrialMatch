# October 24, 2026 Sprint Plan

All times are Eastern. Internal deadline and feature freeze: **6:30 PM**.

| Sprint | Target | Shared / Clinical Intelligence | Geographic Intelligence / Optimization | Exit evidence |
|---|---:|---|---|---|
| 0 — Immediate | Start | Shared scaffold, steering, workstream specs, contracts, ownership, environment, provenance manifest, Git synchronization | Branch from the exact verified shared commit | Remote `main` SHA verified; both branches identify same base |
| 1 | 2:00 PM | Trial ingestion, normalized records, source verification, search API | MassGIS ingestion, schema/count verification, normalized geography | Actual source metadata and targeted ingestion/API tests |
| 2 | 3:15 PM | Structured extraction, deterministic evaluator, tests | Access indicators, site geography, validation tests | Schema-rejection and core correctness tests executed |
| 3 | 4:30 PM | Synthetic matching, explanations, clinical APIs | MILP optimizer, constraints, baseline comparison | Contract examples and deterministic results verified |
| 4 | 5:30 PM | Patient-facing integration and end-to-end contract checks | Researcher map/dashboard integration | Frontend build and critical API journeys executed |
| 5 | 6:00 PM | Fix critical issues, verify scenarios, document limitations, stable commit | Same; verify infeasibility/assumptions and stable commit | Test/build output recorded honestly; blockers documented |
| 6 | 6:00–6:30 PM | Feature freeze, reproducibility and final integration only | Feature freeze, reproducibility and final integration only | Demo path, public build, repo, video, licenses/privacy/IP checklist |

## Scheduling policy

- At execution start, compare the actual Eastern time with the targets above. Do not spend time completing an expired breadth goal if it threatens the core engine.
- Clinical priority: source ingestion → validated rule structure → deterministic evaluator → evidence → APIs → tests → UI → polish.
- Geographic priority: source ingestion → validated indicators → honest optimization model → baseline/feasibility → APIs/tests → map/UI.
- Reduce the number of detailed studies or visual scope before reducing correctness, uncertainty handling, provenance, or traceability.
- No new feature work begins after 6:00 PM. The last 30 minutes are for reproducibility, integration, documentation, and submission verification.

## Handoffs

1. Sprint 0 records the shared commit SHA in team communication.
2. Clinical publishes stable trial/site exchange fields through the shared contract; geography does not import clinical internals.
3. Any shared contract change is proposed before frontend work depends on it and acknowledged by both owners.
4. Each workstream reports the exact commands run, observed result, unresolved source failures, and commit SHA.
5. Final integration preserves both owners' histories and does not silently resolve conflicts by discarding work.
