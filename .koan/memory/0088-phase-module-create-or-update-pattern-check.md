---
title: 'Phase module create-or-(re-decompose) pattern: check artifact existence at
  step 1 to determine mode; routine UPDATE moved to producer-pair phase'
type: procedure
created: '2026-04-23T13:25:59Z'
modified: '2026-04-26T09:38:47Z'
---

The `milestone-spec` phase module in koan (`koan/phases/milestone_spec.py`) was designed on 2026-04-23 by Leon to check artifact existence at step 1 to determine mode. The determining factor: whether `milestones.md` exists in the run directory.

On 2026-04-23, Leon documented the original CREATE-or-UPDATE pattern: if `milestones.md` does not exist, CREATE mode (decompose initiative); if it exists, UPDATE mode (mark completed `[done]`, add Outcome, advance next `[pending]`). Designed as a reusable pattern for koan phase modules that own an artifact: check artifact existence at step 1 to determine mode, write the artifact at step 2 via the artifact-write tool. Mirrors how plan-spec handles re-runs after plan-review surfaces problems.

On 2026-04-26, Leon retired milestone-spec UPDATE mode. Routine post-execution UPDATE responsibility moved to exec-review (because exec-review structurally always follows execute, the trigger is structural). milestone-spec retains the CREATE-or-non-CREATE branching pattern but the non-CREATE branch is now RE-DECOMPOSE: the user explicitly redirects to milestone-spec after a major deviation that requires changing the milestone graph itself; the phase revises `[pending]` and `[in-progress]` sketches but never marks milestones `[done]` or adds Outcome sections. The reusable design pattern survives: phase modules that own an artifact check existence at step 1; the non-CREATE branch's behaviour depends on whether routine UPDATE belongs to this phase (CREATE+UPDATE pattern) or has been moved to a producer-pair phase (CREATE+RE-DECOMPOSE pattern, as with milestone-spec).
