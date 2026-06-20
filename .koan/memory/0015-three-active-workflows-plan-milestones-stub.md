---
title: 'Five active workflows: discovery, plan, milestones, initiative (delivery hierarchy)
  + curation (orthogonal)'
type: context
created: '2026-04-16T08:37:42Z'
modified: '2026-06-20T03:59:04Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
---

The koan workflow registry (`koan/lib/workflows.py`) registers five workflow presets that compose into a four-tier delivery hierarchy by ceremony level plus one orthogonal maintenance preset:

- `discovery` (single phase: `frame`) -- open-ended divergent exploration when the user is not yet sure what they want; the agent is a sounding board; exit is user-driven via koan_set_workflow or koan_set_phase (including setting the phase to the terminal 'done').
- `plan` -- focused change touching a bounded area; single executor handoff. Sequence: intake -> plan -> execute -> curation.
- `milestones` -- multi-milestone initiative with implicit codebase-derived architecture. Sequence: intake -> milestone -> plan -> execute -> (loop back to plan per remaining milestone) -> curation.
- `initiative` -- multi-milestone initiative with an explicit architectural design band; adds to brief.md the companion artifacts core-flows.md (frozen, behavioral spec) and tech-plan.md (disposable, structural spec). Sequence: intake -> core-flows -> tech-plan -> milestone -> plan -> execute -> (loop) -> curation.
- `curation` -- single-phase orthogonal preset for standalone memory maintenance.

The full phase set is {intake, core-flows, tech-plan, milestone, plan, execute, curation, frame}; there are no separate *-review phases. Review is mechanical (a reviewer sub-agent spawned on koan_artifact_write for reviewed artifact families) and the execute phase performs inline post-execution review. Users can deviate from any preset's auto-advance defaults at any yield boundary because `is_valid_transition` permits any-to-any movement within a workflow's available phases except self-transition.
