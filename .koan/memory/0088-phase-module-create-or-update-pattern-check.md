---
title: 'Phase module create-or-update pattern: check artifact existence at step 1
  to determine mode'
type: procedure
created: '2026-04-23T13:25:59Z'
modified: '2026-04-23T13:25:59Z'
---

The `milestone-spec` phase module in koan (`koan/phases/milestone_spec.py`) was designed on 2026-04-23 by Leon to serve double duty: initial decomposition of a broad initiative into milestones, and post-execution updates to `milestones.md` after each milestone completes. The determining factor at runtime is whether `milestones.md` exists in the run directory: if it does not exist, the orchestrator is in CREATE mode and decomposes the initiative from intake findings; if it exists, the orchestrator is in UPDATE mode and updates it using exec-review findings from conversation context. Leon documented this as a reusable design pattern for koan phase modules that own an artifact: check artifact existence at step 1 to determine mode (CREATE vs UPDATE); write the artifact at step 2 via `koan_artifact_propose`. No separate update phase is needed -- the spec phase is the write phase for its artifact. This mirrors how plan-spec handles re-runs after plan-review surfaces problems: the orchestrator loops back to plan-spec, which rewrites `plan.md` in full.
