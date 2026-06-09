---
title: 'Mechanical RAG injection anchor: task + run-dir markdown (mtime asc); prior-phase-summary
  source removed'
type: decision
created: '2026-04-17T09:37:31Z'
modified: '2026-04-27T09:01:14Z'
related:
- 0020-memory-retrieval-static-directive-mechanical-injection.md
---

This entry documents the anchor composition rule for koan's mechanical RAG injection pipeline. On 2026-04-17, Leon decided that `_compose_rag_anchor` in `koan/web/mcp_endpoint.py` produces a single anchor string from three sources concatenated in a fixed order: (1) the workflow task description, (2) every `*.md` file in the run directory sorted by mtime ascending (oldest first), (3) the immediate prior phase's summary read from `Run.phase_summaries[completed_phase]`. The cheap query-generation LLM received this single anchor plus the per-phase `retrieval_directive` and produced 1-3 search queries combined and reranked against the directive. Alternatives rejected: separate RAG queries per source (more LLM calls, harder reranking), and including all prior phase summaries (would dilute anchor topics -- relies on summary-chain compaction).

On 2026-04-26, Leon retired the `phase_summaries` capture mechanism in koan. The third source -- prior-phase summary -- was removed from `_compose_rag_anchor`; signature simplified to `(task_description: str, run_dir: str | None) -> str`. The anchor now reduces to task description + run-dir markdown by mtime ascending (sources 1 and 2 only). `brief.md` (the frozen initiative artifact written by intake) serves as the de facto initiative anchor via the run-dir markdown source -- no special treatment needed since it appears among the other run-dir markdown files sorted by mtime. The chronological ordering invariant (most-recent-artifact-closest-to-end) holds because attention is strongest at the anchor's tail end.
