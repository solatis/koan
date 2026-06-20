---
title: PhaseBinding.guidance injected at a no-write step 1 must not contain artifact-write
  calls; pre-transition setup belongs in the originating phase
type: procedure
created: '2026-04-23T15:49:14Z'
modified: '2026-06-20T04:13:23Z'
related:
- 0090-workflow-guidance-injected-at-plan-spec-step-1.md
- 0088-phase-module-create-or-update-pattern-check.md
---

The `PhaseBinding.guidance` injection system (`koan/lib/workflows.py`) lets per-workflow framing be added to any phase module's step 1 guidance. The rule Leon confirmed: if a general-scoped phase module (such as the plan producer) has step 1 guidance that says 'Do NOT write any files in this step,' the per-workflow guidance injected at that step must also contain no artifact-write instructions. When a write instruction appears in a no-write step 1, the orchestrator defers it to step 2, where it collides with step 2's own artifact instructions and creates filename ambiguity. The correct pattern: if phase A needs to set up state before transitioning to phase B (e.g., mark a milestone `[in-progress]` in `milestones.md`), that setup write must happen in phase A's write step, not via phase B's injected guidance. (Artifact creation is `koan_artifact_write` -- write-once, and it spawns the mechanical reviewer; edits are `koan_artifact_edit`.)
