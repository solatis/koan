---
title: PhaseBinding.guidance injected at a no-write step 1 must not contain koan_artifact_propose
  calls; pre-transition setup belongs in the originating phase
type: procedure
created: '2026-04-23T15:49:14Z'
modified: '2026-04-23T15:49:14Z'
related:
- 0090-workflow-guidance-injected-at-plan-spec-step-1.md
- 0088-phase-module-create-or-update-pattern-check.md
---

The `PhaseBinding.guidance` injection system in `koan/lib/workflows.py` allows per-workflow framing to be added to any phase module's step 1 guidance. On 2026-04-23, Leon confirmed the following rule when fixing a milestones workflow bug: if a general-scoped phase module (such as `plan_spec.py`) has step 1 guidance that says "Do NOT write any files in this step," the `PhaseBinding.guidance` injected at step 1 must also not contain `koan_artifact_propose` calls or other write operations. When a write instruction appears in a no-write step 1, the orchestrator defers it to step 2, where it creates artifact filename ambiguity alongside step 2's own artifact instructions. The correct pattern: if phase A needs to set up state before transitioning to phase B (e.g., mark a milestone `[in-progress]` in `milestones.md`), that setup write must happen in phase A's step 2, not via phase B's injected `PhaseBinding.guidance`. In the milestones workflow, the `[pending]->[in-progress]` status update was moved into `milestone_spec.py` step 2 (where `milestones.md` is already written), so `plan-spec`'s guidance only needed to say "find the `[in-progress]` milestone" with no write instruction.
