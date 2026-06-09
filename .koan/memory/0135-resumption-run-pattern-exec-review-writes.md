---
title: Resumption-run pattern -- exec-review writes Resumption guidance header to
  plan-milestone-N.md, user yields to execute, next executor reads guidance first
type: procedure
created: '2026-05-02T07:31:15Z'
modified: '2026-05-02T07:31:15Z'
related:
- 0102-milestonesmd-outcome-schema-integration-points.md
- 0114-safe-deletion-patterns-for-milestone-driven-removals-migrate-callers-before-delete-total-deletion-in-one-change-negative-presence-assertions-why-comments-at-deletion-sites-replace-not-repurpose.md
---

The koan workflow engine (`koan/phases/exec_review.py`, `koan/lib/workflows.py:MILESTONES_WORKFLOW`) supports recovery from partial executor runs through a header-mediated protocol. On 2026-04-29, during the agent-abstraction milestone of the Claude Agent SDK migration, the first executor run completed steps 1-15 of `plan-milestone-1.md` but stopped before completing steps 16-21 -- a circular-import error blocked test collection. The exec-review phase identified the gaps; the agent revised `plan-milestone-1.md` to insert a "Resumption guidance" header above the existing "Approach summary" section, describing what was done versus pending, the required plan amendment, and any ordering constraints discovered during the first run. User directed `koan_set_phase("execute")` with the instruction "Re-run the executor on the revised plan-milestone-N.md". The resumption executor read the "Resumption guidance" header first, applied the documented amendment, and completed the remaining steps. The same pattern applied on 2026-04-30 during the SDK-adapter milestone when a shell-pipeline trap blocked deletion verification. On 2026-04-30, user established the resumption protocol: exec-review writes a "Resumption guidance" header to `plan-milestone-N.md` describing (a) what is done vs pending, (b) any required plan amendments, (c) ordering constraints discovered during the first run; user yields back to execute with a re-run instruction; the next executor reads the resumption guidance before the original plan body. The header is preserved in `plan-milestone-N.md` as a record of the deviation; the "Deviations from plan" subsection of the milestone's eventual Outcome in `milestones.md` captures the same facts at the milestone level.
