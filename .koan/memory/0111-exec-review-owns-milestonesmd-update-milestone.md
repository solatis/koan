---
title: The execute phase owns the milestones.md done/Outcome UPDATE; the milestone
  phase is CREATE + RE-DECOMPOSE only
type: decision
created: '2026-04-26T09:33:11Z'
modified: '2026-06-20T01:00:29Z'
related:
- 0088-phase-module-create-or-update-pattern-check.md
- 0102-milestonesmd-outcome-schema-integration-points.md
---

On 2026-04-26, Leon moved the milestones-workflow loop's routine UPDATE responsibility from milestone-spec to exec-review (`koan/phases/exec_review.py`, `koan/phases/milestone_spec.py`, `koan/lib/workflows.py:_EXEC_REVIEW_MILESTONES_GUIDANCE`). The change: `exec_review.py` step 2 gained a milestones-workflow-only block (gated by per-workflow `phase_instructions`, not hardcoded in the SCOPE="general" module body) that issues `koan_artifact_write` against `milestones.md` to mark the completed milestone `[done]`, append the four-subsection Outcome (Integration points / Patterns / Constraints / Deviations), advance the next `[pending]` to `[in-progress]`, and adjust remaining milestone sketches based on deviations. Prior `[done]` Outcome sections must be preserved intact across rewrites. `milestone_spec.py` UPDATE-mode prompt branches were removed; milestone-spec retained CREATE + manual RE-DECOMPOSE (the user explicitly redirects after a major deviation that requires changing the milestone graph itself) but never marks milestones `[done]` or adds Outcome sections. Trigger is structural: exec-review always follows execute.

**Update (feat/epoch refactor):** exec-review was removed and its responsibilities absorbed by the execute phase. The milestones.md UPDATE -- mark the completed milestone [done], append the four-subsection Outcome, advance the next [pending] -- now happens in the execute phase inline post-execution review, gated by the workflow phase_instructions. The milestone-spec phase was renamed to the milestone phase (CREATE plus re-decompose); re-decomposition discard of non-executed artifacts fires automatically on re-entering the milestone phase. After execute, the transition targets are plan (next milestone), curation (all milestones done), or milestone (manual re-decompose).
