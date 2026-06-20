---
title: 'milestones.md Outcome schema: Integration points / Patterns / Constraints
  / Deviations'
type: decision
created: '2026-04-24T09:30:13Z'
modified: '2026-06-20T04:13:32Z'
related:
- 0087-phasecontext-resets-on-koansetphase-orchestrator.md
- 0088-phase-module-create-or-update-pattern-check.md
---

The `milestones.md` artifact accumulates a per-milestone Outcome section as the milestones/initiative workflow loops `plan -> execute`. Leon endorsed a prescribed structure for every Outcome section with four subsections: **Integration points created** (new interfaces, extension seams, modules subsequent milestones can depend on, named with file paths and identifiers), **Patterns established** (naming, file placement, error handling, and test conventions this milestone committed to that subsequent milestones must match), **Constraints discovered** (things that turned out harder or different than the sketch anticipated -- explicit facts that change what future milestones can assume), and **Deviations from plan** (what the executor did differently from the milestone plan and why). The Outcome section is written by the execute phase's inline post-execution review, with the Deviations-from-plan subsection sourced from that review plus the executor's deviation report. The lifecycle is **additive-forward**: Outcomes are appended and remaining milestones may be revised, but Outcome sections are never deleted -- history stays visible. Status markers: `[pending]`, `[in-progress]`, `[done]`, `[skipped]`. Leon flagged a caveat: the four-subsection structure is engineering judgment, not literature-validated; if a subsection proves routinely empty or overloaded, revise it -- treat it as a starting shape, not a permanent contract.
