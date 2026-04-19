---
title: 'Intake confidence loop removed: unnecessary scout batches and intrinsic self-correction
  risk'
type: lesson
created: '2026-04-16T08:34:26Z'
modified: '2026-04-18T16:21:49Z'
related:
- 0002-step-first-workflow-pattern-boot-prompt-is.md
- 0005-phase-trust-model-plan-review-as-designated.md
- 0013-single-cognitive-goal-per-step-prevents-simulated.md
---

The intake phase in koan (koan/phases/intake.py) previously included a confidence-gated loop where steps 2-4 would repeat based on a structured confidence value. On 2026-04-12, Leon collapsed intake to a focused 2-step design (Gather + Deepen), removing the loop for three reasons: (a) it produced unnecessary second scout batches; (b) the Reflect step risked intrinsic self-correction -- the same LLM verifying its own prior reasoning rather than checking against actual codebase files; (c) a single thorough Deepen pass was sufficient when that step was well-scoped. Phase completion was redefined by depth of understanding, not iteration count.

On 2026-04-17, Leon extracted a dedicated Summarize step from Deepen's conclusion, bringing intake to 3 steps total: Gather, Deepen, Summarize. The split applies the single-cognitive-goal-per-step principle (entry 0013): Deepen stays focused on dialogue and codebase verification; Summarize is a distinct step for synthesizing findings into a planning handoff. The confidence-loop removal rationale is unchanged -- the step count change only separates concerns that were already happening at the end of step 2. Note: docs/intake-loop.md still describes the older 2-step design as of 2026-04-18 and requires a separate update.
