---
title: Workflow guidance injected at plan-spec step 1 caused wrong artifact proposal
  -- deferred write created filename ambiguity at step 2
type: lesson
created: '2026-04-23T15:49:08Z'
modified: '2026-06-19T12:20:26Z'
related:
- 0088-phase-module-create-or-update-pattern-check.md
---

This entry records a bug in the milestones workflow implementation (`koan/lib/workflows.py` and `koan/phases/plan_spec.py`). On 2026-04-23, Leon reported that after transitioning from `milestone-spec` or `milestone-review` to `plan-spec`, the orchestrator proposed `milestones.md` again in plan-spec step 2 instead of the expected `plan-milestone-N.md`. Root cause in `_MILESTONES_PLAN_SPEC_GUIDANCE` (a `PhaseBinding.guidance` string): it told the orchestrator to write `milestones.md` before writing the plan, but plan-spec step 1 says 'Do NOT write any files in this step,' so the model deferred the write to step 2, where the most prominent write target visible in the injected guidance (`milestones.md`) won out over `plan-milestone-N.md`. The fix moved the `[pending]->[in-progress]` status update into the originating phase's write step and removed the write instruction from the plan-spec guidance entirely.

**Update (feat/epoch refactor):** the phases were renamed (plan-spec -> plan, milestone-spec -> milestone) and koan_artifact_propose was removed -- artifact creation is now koan_artifact_write (write-once, which also spawns the mechanical reviewer) and edits use koan_artifact_edit. The specific bug is historical; the underlying lesson still holds (a no-write step-1 guidance must not contain artifact-write instructions or the model defers the write into step 2 and creates filename ambiguity).
