---
title: 'Mechanical RAG injection anchor: task + run-dir markdown (mtime asc); prior-phase-summary
  source removed'
type: decision
created: '2026-04-17T09:37:31Z'
modified: '2026-06-20T03:25:48Z'
related:
- 0020-memory-retrieval-static-directive-mechanical.md
---

koan's mechanical RAG injection composes a single anchor string from two sources, in `_compose_rag_anchor` (`koan/tools/koan_tools.py`): (1) the workflow task description, then (2) every `*.md` file in the run directory sorted by mtime ascending (oldest first). The cheap query-generation LLM receives this anchor plus the per-phase `retrieval_directive` and produces 1-3 search queries, combined and reranked against the directive; the signature is `(task_description: str, run_dir: str | None) -> str`. A third source -- the immediate prior phase's summary -- was originally part of the anchor but was removed when Leon retired the `phase_summaries` capture mechanism; the chronological-ordering invariant (most-recent artifact closest to the anchor's tail) still holds because attention is strongest at the tail end. `brief.md` (the frozen initiative artifact written by intake) serves as the de facto initiative anchor via the run-dir markdown source -- no special treatment, since it sorts among the other run-dir markdown by mtime. Alternatives Leon rejected: separate RAG queries per source (more LLM calls, harder reranking), and including all prior-phase summaries (dilutes anchor topics -- relies on summary-chain compaction).
