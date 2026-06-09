---
title: Single cognitive goal per step -- prevents simulated refinement
type: decision
created: '2026-04-16T08:37:25Z'
modified: '2026-06-05T13:06:08Z'
related:
- 0002-step-first-workflow-pattern-boot-prompt-is.md
- 0010-curation-phase-3-step-layout-collapsed-to-2-to.md
---

The step design constraint for koan phases (documented in `docs/architecture.md`) was established by Leon on 2026-02-10: each phase step must correspond to exactly one cognitive goal. The failure mode it prevents: when a single step combines multiple goals ("do A, then B, then C"), the LLM can engage in "simulated refinement" -- artificially downgrading its output for A to manufacture visible improvement in C without genuinely improving anything. The rule for adding a phase: each step must answer "what is the single thing this step accomplishes?", and if the answer needs an "and then", the step must be split. Reference designs place cognitively distinct operations in separate steps: `koan/phases/plan_spec.py` (Analyze + Write), `koan/phases/intake.py` (Gather + Deepen), `koan/phases/curation.py` (Inventory + Memorize). The isolation is enforced mechanically by the agent loop: after the control-loop change on 2026-06-05 removed `koan_complete_step`, the end-of-turn turn-outcome resolver in `koan/agents/loop.py` injects exactly one step's guidance per turn (previously each step's guidance was pulled by a separate `koan_complete_step` call).
