---
title: 'milestones.md Outcome schema: Integration points / Patterns / Constraints
  / Deviations'
type: decision
created: '2026-04-24T09:30:13Z'
modified: '2026-04-24T09:30:13Z'
related:
- 0087-phasecontext-resets-on-koansetphase-orchestrator.md
- 0088-phase-module-create-or-update-pattern-check.md
---

The `milestones.md` artifact written by `koan/phases/milestone_spec.py` accumulates a per-milestone Outcome section as the milestones workflow loops through `plan-spec -> execute -> exec-review -> milestone-spec (UPDATE)`. On 2026-04-24, Leon endorsed (via Claude Desktop collaboration) a prescribed structure for every Outcome section with four subsections: **Integration points created** (new interfaces, extension seams, modules subsequent milestones can depend on, named with file paths and identifiers), **Patterns established** (naming, file placement, error handling, and test conventions this milestone committed to that subsequent milestones must match), **Constraints discovered** (things that turned out harder or different than the sketch anticipated -- explicit facts that change what future milestones can assume), and **Deviations from plan** (what the executor did differently from `plan-m{N}.md` and why, sourced from exec-review). The lifecycle is **additive-forward**: UPDATE mode appends Outcomes and may revise remaining milestones, but it never deletes Outcome sections -- history stays visible. Status markers remain `[pending]`, `[in-progress]`, `[done]`, `[skipped]`. Leon flagged an honest caveat at endorsement: the four-subsection structure is engineering judgment, not literature-validated; if eval harness runs show certain subsections are routinely empty or routinely overloaded, the structure should be revised. Treat it as a starting shape, not a permanent contract.
