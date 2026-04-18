---
title: 'Mechanical RAG injection anchor: task + run-dir markdown (mtime asc) + immediate
  prior phase summary'
type: decision
created: '2026-04-17T09:37:31Z'
modified: '2026-04-17T09:37:31Z'
related:
- 0020-memory-retrieval-static-directive-mechanical-injection.md
- 0041-per-phase-summary-capture-rides-on-orchestrators.md
---

This entry documents the anchor composition rule for koan's mechanical RAG injection pipeline. On 2026-04-17, user decided that `_compose_rag_anchor` in `koan/web/mcp_endpoint.py` produces a single anchor string from three sources concatenated in a fixed order: (1) the workflow task description, (2) every `*.md` file in the run directory sorted by mtime ascending (oldest first), (3) the immediate prior phase's summary read from `Run.phase_summaries[completed_phase]`. The cheap query-generation LLM receives this single anchor plus the per-phase `retrieval_directive` and produces 1-3 search queries combined and reranked against the directive. Alternatives rejected: separate RAG queries per source (more LLM calls, harder reranking -- user noted "it's more common to do a single context and guide the cheap LLM into writing useful queries based on all provided context"), and including all prior phase summaries (would dilute anchor topics -- relies on summary-chain compaction: if intake facts still matter in plan-review, plan-spec's summary repeats them). Chronological mtime ordering puts the most recent artifact closest to the prior summary, placing the most directly relevant content where attention is strongest. Decision surfaced during 2026-04-17 intake when user clarified the anchor should be "first task description, then all artifacts in chronological order, then summary of previous phase".
