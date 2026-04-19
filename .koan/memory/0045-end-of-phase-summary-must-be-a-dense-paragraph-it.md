---
title: End-of-phase summary must be a dense paragraph -- it becomes the next phase's
  RAG anchor
type: procedure
created: '2026-04-17T09:37:55Z'
modified: '2026-04-17T09:37:55Z'
related:
- 0041-per-phase-summary-capture-rides-on-orchestrators.md
- 0043-mechanical-rag-injection-anchor-task-run-dir.md
---

This entry records a behavioral rule for koan orchestrator agents at phase boundaries. On 2026-04-17, the team established the procedure: when the orchestrator is about to call its first `koan_yield` of a phase boundary (the `Phase Complete` boundary that follows the final `koan_complete_step` of a phase), the assistant text immediately preceding that yield must be a standalone, dense, information-rich paragraph that names the decisions made, constraints discovered, artifacts produced, and any unresolved items of the just-finished phase. The rule exists because that text is automatically captured into `Run.phase_summaries[phase]` and fed as the prior-phase summary anchor for the next phase's mechanical RAG injection (see `_extract_last_orchestrator_text` in `koan/web/mcp_endpoint.py`). A terse "done" or single-sentence acknowledgement degrades the next phase's RAG retrieval quality and degrades the user-facing brief. Procedure derived during the 2026-04-17 RAG-wiring workflow. Mechanical reinforcement: an `IMPORTANT:` paragraph in the orchestrator system prompt (`koan/prompts/orchestrator.py`) instructs the orchestrator about the contract; future drift is observable via warning logs when `len(summary_text) < 50` chars or when no text is captured at all.
