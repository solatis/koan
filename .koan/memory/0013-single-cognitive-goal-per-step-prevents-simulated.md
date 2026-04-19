---
title: Single cognitive goal per step -- prevents simulated refinement
type: decision
created: '2026-04-16T08:37:25Z'
modified: '2026-04-16T08:37:25Z'
related:
- 0002-step-first-workflow-pattern-boot-prompt-is.md
- 0010-curation-phase-3-step-layout-collapsed-to-2-to.md
---

The step design constraint for koan phases (`docs/architecture.md` -- Pitfalls section, "Don't give a step multiple cognitive goals") was established on 2026-02-10 when Leon set a rule: each `koan_complete_step` call must correspond to exactly one cognitive goal. Leon identified the failure mode that motivated this rule: when a single step combines multiple goals ("do A, then B, then C"), the LLM can engage in "simulated refinement" -- artificially downgrading its output for A in order to manufacture visible improvement in C, without genuinely improving anything. Leon documented this as a design constraint: when adding a new phase, each step must answer "what is the single thing this step accomplishes?" and if the answer requires "and then," the step must be split. Leon's reference designs in `koan/phases/plan_spec.py` (Analyze + Write), `koan/phases/intake.py` (Gather + Deepen), and `koan/phases/curation.py` (Inventory + Memorize) each place cognitively distinct operations into separate `koan_complete_step` calls.
