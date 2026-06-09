---
title: 'Five active workflows: discovery, plan, milestones, initiative (delivery hierarchy)
  + curation (orthogonal)'
type: context
created: '2026-04-16T08:37:42Z'
modified: '2026-04-29T06:01:14Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
---

The koan workflow registry (`koan/lib/workflows.py`) registers five workflow presets as of 2026-04-29 when Leon implemented the initiative and discovery presets in addition to the existing plan, milestones, and curation presets. The five presets compose into a four-tier delivery hierarchy by ceremony level plus one orthogonal maintenance preset:

- `discovery` (single phase: `frame`) -- open-ended divergent exploration when the user is not yet sure what they want; the agent is a sounding board; exit is user-driven via koan_set_workflow, koan_set_phase, or koan_set_phase("done"). Mirrors the existing CURATION_WORKFLOW shape.
- `plan` -- focused change touching a bounded area: intake -> plan-spec -> plan-review -> execute -> exec-review -> curation. Single executor handoff.
- `milestones` -- multi-milestone initiative with implicit codebase-derived architecture: intake -> milestone-spec -> milestone-review -> plan-spec -> plan-review -> execute -> exec-review (loops back to plan-spec per remaining milestone) -> curation. Established 2026-04-23 (replaced an earlier 1-phase stub from 2026-04-16).
- `initiative` -- multi-milestone initiative with explicit architectural design band: intake -> core-flows -> tech-plan-spec -> tech-plan-review -> milestone-spec -> milestone-review -> plan-spec -> plan-review -> execute -> exec-review (loops) -> curation. Adds brief.md companion artifacts core-flows.md (frozen, behavioral spec) and tech-plan.md (disposable, structural spec). Established 2026-04-29.
- `curation` -- single-phase orthogonal preset for standalone memory maintenance.

Users can deviate from any preset's auto-advance defaults at any yield boundary because is_valid_transition permits any-to-any movement within a workflow's available phases except self-transition. The 2026-04-23 stubs-to-full-pipeline transition for `milestones` and the 2026-04-29 addition of `initiative` and `discovery` together establish the five-preset taxonomy.
