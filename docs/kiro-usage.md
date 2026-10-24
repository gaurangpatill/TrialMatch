# Kiro Usage Record

This document distinguishes configured workflow from work actually performed. Update it only with verifiable usage.

## Established in shared scaffold

- Root `.kiro/` is committed and explicitly unignored.
- `.kiro/steering/project.md` captures persistent architecture, safety, provenance, ownership, testing, and Git rules.
- Separate Kiro specs define requirements, design, tasks, acceptance criteria, and verification for Clinical Intelligence and Geographic Intelligence/Optimization.
- `AGENTS.md` provides cross-environment branch and ownership boundaries.

These artifacts establish spec-driven development; they do not prove that future tasks, tests, hooks, MCP servers, or Kiro Powers were used.

## Usage log

| Date | Workstream | Kiro capability | Verifiable artifact/result |
|---|---|---|---|
| 2026-10-24 | Shared scaffold | Steering and spec-driven planning | `.kiro/steering/project.md`; both workstream spec directories |
| 2026-10-24 | Clinical Intelligence | Spec-guided implementation and verification | Tasks C1–C4 and C6–C8 complete; 60-test pytest suite including Hypothesis properties; live LLM run blocked |
| 2026-10-24 | Patient Portal | Frontend contract and safety verification | 5 Vitest proxy tests, TypeScript check, production build, and zero-vulnerability npm audit |
| 2026-10-24 | Clinical Intelligence | Context gathering and semantic review | Branch/spec audit followed by confirmed safety-boundary fixes before final commit |

## Optional capabilities

Hooks may be added only when they provide real value (for example, a finite targeted test command after relevant saves). Property-based testing should target meaningful invariants such as evaluator determinism, polarity, and optimizer resource constraints. MCP integrations and Kiro Powers should be used only if installed, supported, and useful.

Do not claim optional capabilities until their configuration and actual use are recorded. Never create a hook that starts a watcher, leaks environment data, or blocks normal work without a documented reason.

## Final submission update checklist

- Record meaningful Kiro-assisted requirements/design/implementation and review work.
- Link claims to committed specs, steering, hooks, tests, or generated artifacts.
- Record actual commands and outcomes without fabricating success.
- Explain where human decisions constrained architecture, safety, and scope.
- Confirm the feature description matches the deployed build.
