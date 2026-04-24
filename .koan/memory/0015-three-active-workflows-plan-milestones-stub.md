---
title: 'Three active workflows: plan, milestones (full pipeline), curation'
type: context
created: '2026-04-16T08:37:42Z'
modified: '2026-04-23T13:25:54Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
---

The koan workflow registry (`koan/lib/workflows.py`) was updated on 2026-04-23 when Leon implemented the milestones workflow, replacing the stub definition that had existed since 2026-04-16. The `milestones` workflow was previously a 1-phase stub that ran intake only and yielded with no further phases. As of 2026-04-23, the milestones workflow is a full 8-phase delivery pipeline: intake -> milestone-spec -> milestone-review -> plan-spec -> plan-review -> execute -> exec-review -> curation. The orchestrator loops through milestones by reading `milestones.md` at each phase entry: milestone-spec decomposes or updates, plan-spec writes `plan-milestone-N.md` for the current `[in-progress]` milestone, execute hands off to an executor subagent, exec-review verifies the result, then milestone-spec updates `milestones.md` (marks milestone `[done]`, adjusts remaining milestones). The loop continues until all milestones are `[done]` or `[skipped]`, then transitions to curation. The `plan` workflow was also updated: exec-review was added as a phase after execute and before curation.
