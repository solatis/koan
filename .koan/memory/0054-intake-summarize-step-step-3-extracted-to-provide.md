---
title: Intake step 3 (Summarize) writes brief.md via koan_artifact_write; previously
  emitted prose synthesis for phase_summaries capture
type: decision
created: '2026-04-18T16:28:03Z'
modified: '2026-04-26T09:38:35Z'
related:
- 0011-intake-confidence-loop-removed-unnecessary-scout.md
- 0013-single-cognitive-goal-per-step-prevents-simulated.md
- 0041-per-phase-summary-capture-rides-on-orchestrators.md
- 0045-end-of-phase-summary-must-be-a-dense-paragraph-it.md
---

The intake phase in koan (`koan/phases/intake.py`) had its step 3 (Summarize, TOTAL_STEPS=3) extracted from the end of step 2 (Deepen) on 2026-04-17, then progressively repurposed across the unified-artifact-flow initiative on 2026-04-25/26.

On 2026-04-18, Leon confirmed the original rationale: the RAG injection pipeline (entry 0041 -- now deprecated) captured the orchestrator's last prose turn before the first `koan_yield` of each phase as the phase summary. Embedding the synthesis at the end of step 2 risked the synthesis being displaced as the final text before yield. The dedicated Summarize step forced synthesis as its own distinct cognitive act. Secondary rationale: single-cognitive-goal-per-step principle (entry 13).

On 2026-04-25, during M2 of the unified-artifact-flow initiative, Leon broadened intake step 3's responsibility: in addition to composing the chat prose synthesis, the step now writes `brief.md` to the run directory via `koan_artifact_write(filename="brief.md", content=BODY, status="Final")` with the seven-section structure from memory entry 101 (Initiative / Scope / Affected subsystems / Decisions / Constraints / Assumptions / Open questions). The chat synthesis was retained alongside brief.md production specifically to feed the `phase_summaries` capture during the M2->M5 interim.

On 2026-04-26, during M5, Leon removed `phase_summaries` capture entirely (entry 41 deprecated); the chat-synthesis section in intake step 3 was deleted in the same change to avoid leaving dead prose. Step 3 now writes brief.md as its sole output; PHASE_ROLE_CONTEXT's "## Your output" block was tightened to reflect this. Brief.md serves as the new RAG anchor for downstream phases via the run-dir markdown source in `_compose_rag_anchor` (entry 43 updated).
