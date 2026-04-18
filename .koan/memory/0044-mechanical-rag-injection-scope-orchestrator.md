---
title: 'Mechanical RAG injection scope: orchestrator phases only; curation excluded'
type: decision
created: '2026-04-17T09:37:43Z'
modified: '2026-04-17T09:37:43Z'
related:
- 0020-memory-retrieval-static-directive-mechanical-injection.md
---

This entry documents the agent-type scope for koan's mechanical RAG memory injection. On 2026-04-17, user decided that mechanical injection runs ONLY for orchestrator phases that declare a non-empty `retrieval_directive` on their `PhaseBinding` in `koan/lib/workflows.py`. Scouts and executors are excluded from injection. The curation phase's binding sets `retrieval_directive=""` explicitly, disabling injection. Rationale: scouts receive a narrow single-shot prompt where memory entries would be noise; executors have richer artifacts to read and benefit less from cross-cutting memory; curation already calls `koan_memory_status` which surfaces the full project summary and entry listing, making mechanical injection redundant for it. Alternatives rejected: include executors with a directive keyed to artifact subsystems (deferred to a future workflow because executors don't yet have a clear directive vocabulary), and emit a non-empty curation directive (rejected because `koan_memory_status` already covers the duplicate-detection use case). Scope surfaced during 2026-04-17 intake when user explicitly answered "orchestrator_only" to the agent-scope question.
