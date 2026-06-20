---
title: plan-m{N}.md is disposable; compresses into milestone Outcome after execution
type: decision
created: '2026-04-24T09:30:17Z'
modified: '2026-06-20T04:28:16Z'
---

The plan artifact in koan (`plan-milestone-N.md` in the milestones/initiative workflows, `plan.md` in the plan workflow) is **disposable**, a lifecycle Leon endorsed: written once per milestone (or once per plan-workflow run) by the producer plan phase, revised in place only when the mechanical PLAN_REVIEWER -- spawned automatically on `koan_artifact_write` of the plan -- surfaces Critical/Major issues, consumed by the executor subagent, then compressed into the milestone's Outcome section after the execute phase's inline post-execution review. Future plans reference the Outcome section, not the prior plan artifact. This distinguishes plans from `brief.md` (frozen, stable) and `milestones.md` (additive-forward, history visible). Must-not-contain rules for plans: exclude requirements rationale (belongs in `brief.md`), exclude cross-milestone concerns (belong in `brief.md` + `milestones.md`), and exclude actual code (a plan is file-level instructions, not implementation). Plans reference only real files, functions, and types.
