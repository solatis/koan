---
title: Plan analysis must inventory non-source consumers (eval harness, scripts, integration
  tests) when removing koan-core fields
type: lesson
created: '2026-04-26T13:25:41Z'
modified: '2026-06-19T12:21:10Z'
related:
- 0049-eval-solver-answers-all-koan-interactive-gates.md
- 0089-proactively-capture-memory-updates-for-discovered.md
- 0114-safe-deletion-patterns-for-milestone-driven.md
---

This entry records a defect in a plan-spec analysis for an inline-review backend removal in koan. On 2026-04-26, the analysis deliberately scoped the change to delete `phase_summaries` from `koan/projections.py:Run`, the corresponding fold case, the `phase_summary_captured` event, and the capture block in `koan_yield`. The 'Files NOT modified' list correctly named the eval-fixture pinned snapshot and the compiled frontend bundles but did NOT enumerate the active eval-harness modules (`evals/harvest.py`, `evals/scorers.py`, `evals/rubrics.py`, `evals/runner.py`, `tests/evals/`) which import koan types and consume the `phase_summaries` field directly. The defect surfaced post-implementation only because Leon explicitly asked during curation whether the eval framework's use of summaries had been accounted for -- without that steering, the dogfooded run would have shipped with broken eval harvest (AttributeError on the deleted field) and degraded scoring. Root cause: the analysis enumerated source-tree consumers (phase prompts, system prompts, permission fence) but not non-source consumers (eval harness, scripts, integration tests, doc snippets).

Lesson: when removing a field from `koan/projections.py`, `koan/state.py`, `koan/events.py`, or any koan-core type, inventory non-source consumers in addition to source-tree callers -- eval harness modules, scripts that parse koan state, integration tests, doc snippets exemplifying the field's shape, and any `*.py` importing from those core modules. The 'Files NOT modified' list must be exhaustive enough to cover all dependents.

**Update (feat/epoch refactor):** the analyzing phase plan-spec was renamed to the plan phase; the lesson is otherwise unchanged and phase-agnostic.
