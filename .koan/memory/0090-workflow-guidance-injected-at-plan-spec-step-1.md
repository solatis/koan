---
title: Workflow guidance injected at plan-spec step 1 caused wrong artifact proposal
  -- deferred write created filename ambiguity at step 2
type: lesson
created: '2026-04-23T15:49:08Z'
modified: '2026-04-23T15:49:08Z'
related:
- 0088-phase-module-create-or-update-pattern-check.md
---

This entry records a bug in the milestones workflow implementation in koan (`koan/lib/workflows.py` and `koan/phases/plan_spec.py`). On 2026-04-23, Leon reported that after transitioning from `milestone-spec` or `milestone-review` to `plan-spec`, the orchestrator proposed `milestones.md` again in plan-spec step 2 instead of the expected `plan-milestone-N.md`. Investigation on 2026-04-23 identified the root cause in `_MILESTONES_PLAN_SPEC_GUIDANCE` (a `PhaseBinding.guidance` string in `koan/lib/workflows.py`): it told the orchestrator to call `koan_artifact_propose` to update `milestones.md` before writing the plan. However, `plan_spec.py` step 1 says "Do NOT write any files in this step," so the model deferred the write to step 2. Plan-spec step 2 instructed the orchestrator to call `koan_artifact_propose` using "the filename from workflow guidance (step 1); default: plan.md." With `milestones.md` as the most prominent `koan_artifact_propose` target visible in the injected guidance, the orchestrator proposed it instead of `plan-milestone-N.md`. The fix -- confirmed clean with 659/659 tests -- moved the `[pending]->[in-progress]` status update into `milestone_spec.py` step 2, and rewrote `_MILESTONES_PLAN_SPEC_GUIDANCE` to remove the write instruction entirely.
