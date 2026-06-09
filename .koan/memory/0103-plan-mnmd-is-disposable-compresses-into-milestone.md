---
title: plan-m{N}.md is disposable; compresses into milestone Outcome after execution
type: decision
created: '2026-04-24T09:30:17Z'
modified: '2026-04-24T09:30:17Z'
---

The plan artifact in koan (`plan-m{N}.md` in the milestones workflow, `plan.md` in the plan workflow) is produced by `koan/phases/plan_spec.py`. On 2026-04-24, Leon endorsed its lifecycle via Claude Desktop collaboration as **disposable**: written once per milestone (or once per plan-workflow run), revised in place only if plan-review surfaces Critical/Major issues, consumed by plan-review and by the executor subagent, then compressed into the milestone's Outcome section after exec-review completes. Future plans reference the Outcome section, not the prior plan artifact. This distinguishes plans from `brief.md` (frozen, stable) and `milestones.md` (additive-forward, history visible). The agreed must-not-contain rules for plans: exclude requirements rationale (belongs in `brief.md`), exclude cross-milestone concerns (belong in `brief.md` + `milestones.md`), and exclude actual code (a plan is file-level instructions, not implementation). Plans must reference only real files, functions, and types -- content sources are `brief.md` (constraints, decisions, affected subsystems), `milestones.md` current-milestone sketch and prior Outcomes (milestones workflow only), the codebase files to modify, and project memory.
