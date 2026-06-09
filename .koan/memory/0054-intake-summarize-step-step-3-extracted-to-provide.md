---
title: Intake's Summarize step writes brief.md via koan_artifact_write; previously
  emitted prose synthesis for phase_summaries capture
type: decision
created: '2026-04-18T16:28:03Z'
modified: '2026-06-02T14:08:32Z'
related:
- 0011-intake-confidence-loop-removed-unnecessary-scout.md
- 0013-single-cognitive-goal-per-step-prevents-simulated.md
- 0101-intake-produces-briefmd-as-a-frozen-handoff.md
---

The intake phase in koan (`koan/phases/intake.py`) gained a dedicated Summarize step on 2026-04-17, extracted from the end of the preceding Deepen step. The Summarize step's responsibility was then progressively repurposed on 2026-04-25 and 2026-04-26.

On 2026-04-18, Leon confirmed the original rationale: the now-retired RAG injection pipeline captured the orchestrator's last prose turn before the first `koan_yield` of each phase as the phase summary. Embedding the synthesis at the end of the Deepen step risked the synthesis being displaced as the final text before yield. The dedicated Summarize step forced synthesis as its own distinct cognitive act. Secondary rationale: the single-cognitive-goal-per-step principle.

On 2026-04-25, Leon broadened the Summarize step's responsibility: in addition to composing the chat prose synthesis, the step now writes `brief.md` to the run directory via `koan_artifact_write(filename="brief.md", content=BODY)` with a seven-section structure (Initiative / Scope / Affected subsystems / Decisions / Constraints / Assumptions / Open questions). The chat synthesis was retained alongside brief.md production specifically to feed the `phase_summaries` capture during the transitional period. (The `koan_artifact_write` status argument that originally accompanied this call was removed from the tool on 2026-06-02.)

On 2026-04-26, Leon removed `phase_summaries` capture entirely; the chat-synthesis section in the Summarize step was deleted in the same change to avoid leaving dead prose. The Summarize step now writes brief.md as its sole output; PHASE_ROLE_CONTEXT's "## Your output" block was tightened to reflect this. brief.md serves as the new RAG anchor for downstream phases via the run-dir markdown source in `_compose_rag_anchor`.
