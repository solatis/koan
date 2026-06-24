---
title: Inline-review phase guidance emitted edit_type='append', a capability the anchored
  editor never had, crashing every review reconciliation
type: lesson
created: '2026-06-24T03:42:06Z'
modified: '2026-06-24T03:42:06Z'
related:
- 0146-agentsmd-describing-functions-that-do-not-yet.md
- 0242-koan-reviewer-findings-are-reconciled-inline-in-a.md
- 0248-a-path-scope-guard-that-raised-instead-of.md
---

koan's plan, milestone, and tech-plan producer phases (`step_guidance` in koan/phases/plan_spec.py, koan/phases/milestone_spec.py, koan/phases/tech_plan_spec.py) instructed the orchestrator to append the inline `## Review` section by calling koan_artifact_edit with anchor="" and edit_type="append". The anchored edit engine (apply_anchored_edit in koan/tools/line_anchors.py) accepts only `replace`, `insert_before`, and `insert_after`, and an empty anchor fails resolution -- so every review reconciliation raised `edit_failed: unknown edit_type 'append'` and crashed the orchestrator with exit_code=1. Root cause: the change that moved reviewer findings inline (replacing the .review.md sidecar) shipped the prompt side but not the tool side -- guidance prescribed a tool capability that was never built, and the two halves were committed out of lockstep. Prevention: when phase guidance prescribes a specific tool call, every parameter value it uses must be a capability the tool actually supports, and guidance must change in the same commit as the tool capability, never prompt-first. This is the prompt-prescribes-nonexistent-capability sibling of the failure mode where AGENTS.md described functions that did not yet exist and pressured executors to create them.
