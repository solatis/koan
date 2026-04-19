---
title: Intake Summarize step (step 3) extracted to provide a clean RAG-injection anchor
  at phase boundary
type: decision
created: '2026-04-18T16:28:03Z'
modified: '2026-04-18T16:28:03Z'
related:
- 0011-intake-confidence-loop-removed-unnecessary-scout.md
- 0013-single-cognitive-goal-per-step-prevents-simulated.md
- 0041-per-phase-summary-capture-rides-on-orchestrators.md
- 0045-end-of-phase-summary-must-be-a-dense-paragraph-it.md
---

The intake phase in koan (koan/phases/intake.py) has a dedicated step 3 (Summarize, TOTAL_STEPS = 3) that was extracted from the end of the Deepen step on 2026-04-17. On 2026-04-18, Leon confirmed the primary rationale: the RAG injection pipeline (entries 0041, 0045) captures the orchestrator's last prose turn before the first koan_yield of each phase as the phase summary. When the synthesis was embedded at the end of step 2 (Deepen), any koan_complete_step call for remaining Deepen work would follow the synthesis text, potentially displacing it as the final text before yield and leaving the RAG capture with noisy or incomplete content.

The dedicated Summarize step forces synthesis to happen as its own distinct act immediately before the phase boundary, so the prose written between the phase-complete koan_complete_step response and the first koan_yield is an unambiguous summary -- the form the RAG pipeline expects. Secondary rationale: the single-cognitive-goal-per-step principle (entry 0013) -- Deepen stays focused on dialogue and verification; Summarize is a distinct cognitive act. Alternative rejected: embedding the summary at the end of step 2 and relying on step discipline alone, because the RAG capture mechanism has no way to enforce which portion of step 2's output is the synthesis.
