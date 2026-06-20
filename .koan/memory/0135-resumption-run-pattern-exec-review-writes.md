---
title: 'Resumption-run pattern: the execute phase writes a Resumption guidance header
  to plan-milestone-N.md; the next executor reads it before the plan body'
type: procedure
created: '2026-05-02T07:31:15Z'
modified: '2026-06-20T04:28:47Z'
related:
- 0102-milestonesmd-outcome-schema-integration-points.md
- 0114-safe-deletion-patterns-for-milestone-driven-removals-migrate-callers-before-delete-total-deletion-in-one-change-negative-presence-assertions-why-comments-at-deletion-sites-replace-not-repurpose.md
---

koan recovers from partial executor runs through a header-mediated protocol driven from the execute phase. When an executor completes only some steps of `plan-milestone-N.md` and stops (for example, blocked by a circular-import error that breaks test collection), the execute phase's inline post-execution review identifies the gaps and revises the plan: it inserts a 'Resumption guidance' header above the existing 'Approach summary' section describing (a) what is done versus pending, (b) any required plan amendments, (c) ordering constraints discovered during the first run. The run is then re-executed via `koan_set_phase("execute", plan_file=...)`; the resumption executor reads the guidance header before the original plan body, applies the amendment, and completes the remaining steps. The header stays in the plan as a record of the deviation, and the 'Deviations from plan' subsection of the milestone's eventual Outcome in `milestones.md` captures the same facts at the milestone level. Leon established this protocol.
