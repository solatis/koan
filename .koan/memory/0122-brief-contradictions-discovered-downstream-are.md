---
title: Brief contradictions discovered downstream are resolved in the consumer artifact,
  not by amending the frozen brief
type: procedure
created: '2026-04-29T03:48:13Z'
modified: '2026-04-29T03:48:13Z'
related:
- 0101-intake-produces-brief-md-as-a-frozen-handoff-artifact.md
- 0110-review-phase-rewrite-or-loop-back-semantics-replace-advisory-only-doctrine.md
- 0117-plan-review-reviewer-scope-narrowed-drop-mechanical-claim-verification-add-docstring-discipline-check.md
---

The koan plan workflow's brief.md is a frozen handoff artifact written by intake. On 2026-04-28, plan-review surfaced an internal contradiction in a brief: two clauses of one Decision were mutually inconsistent because the combination left no constructible path for the feature being specified. Plan-review used `koan_ask_question` to ask the user which clause should win; the user picked one. The resolution was recorded as an explicit `## Brief reconciliation note` section at the top of `plan.md`, with the affected Decision in the plan reflecting the chosen reading; `brief.md` was NOT touched. The pattern: when a downstream phase (plan-review, milestone-review, exec-review, or the executor itself) discovers that brief.md is internally contradictory or that respecting one of its clauses would block another, the phase surfaces the contradiction via `koan_ask_question` (or via `koan_yield` if questions are restricted), records the user's resolution in the consumer artifact it owns (`plan.md`, the milestone plan, the milestone Outcome, etc.), and proceeds. The frozen-brief invariant is preserved: brief.md remains the historical record of what intake produced and what the user agreed to at intake exit; the consumer artifact carries the explicit override with attribution to the resolving phase, so replay and audit see the disagreement instead of an erased rewrite. Silent amendment of brief.md remains prohibited.
