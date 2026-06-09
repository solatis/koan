---
title: exec-review owns milestones.md UPDATE; milestone-spec becomes CREATE + RE-DECOMPOSE
type: decision
created: '2026-04-26T09:33:11Z'
modified: '2026-04-26T09:33:11Z'
related:
- 0088-phase-module-create-or-update-pattern.md
- 0102-milestonesmd-outcome-schema-integration-points.md
---

On 2026-04-26, Leon moved the milestones-workflow loop's routine UPDATE responsibility from milestone-spec to exec-review (`koan/phases/exec_review.py`, `koan/phases/milestone_spec.py`, `koan/lib/workflows.py:_EXEC_REVIEW_MILESTONES_GUIDANCE`, `MILESTONES_WORKFLOW.transitions["exec-review"]`). The change: `exec_review.py` step 2 gained a milestones-workflow-only block (gated by per-workflow `phase_instructions` from `_EXEC_REVIEW_MILESTONES_GUIDANCE`, not hardcoded in the SCOPE="general" module body) that issues `koan_artifact_write` against `milestones.md` to mark the completed milestone `[done]`, append the four-subsection Outcome (Integration points / Patterns / Constraints / Deviations), advance the next `[pending]` to `[in-progress]`, and adjust remaining milestone sketches based on deviations. Prior `[done]` Outcome sections must be preserved intact across rewrites. `milestone_spec.py` UPDATE-mode prompt branches were removed; milestone-spec retains CREATE + manual RE-DECOMPOSE entry path (where the user explicitly redirects after a major deviation that requires changing the milestone graph itself) but never marks milestones `[done]` or adds Outcome sections. `MILESTONES_WORKFLOW.transitions["exec-review"]` reordered to `["plan-spec", "curation", "milestone-spec"]` -- plan-spec (next milestone) is the most common path; curation (all done) is second-most-common; milestone-spec (manual RE-DECOMPOSE) is the rare override. Plan-workflow exec-review is unaffected because no `milestones.md` exists; `_EXEC_REVIEW_PLAN_GUIDANCE` does not reference the UPDATE block. Trigger is structural: exec-review always follows execute, so the routine post-execution UPDATE happens there.
