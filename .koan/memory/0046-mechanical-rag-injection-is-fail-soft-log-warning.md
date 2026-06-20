---
title: 'Mechanical RAG injection is fail-soft: log warning, never block phase handshake'
type: procedure
created: '2026-04-17T09:38:05Z'
modified: '2026-06-20T03:25:55Z'
---

koan's mechanical memory injection at the orchestrator's phase handshake is fail-soft. When `_compute_memory_injection_core` in `koan/tools/koan_tools.py` raises any exception (missing `VOYAGE_API_KEY`, empty `.koan/memory/`, LanceDB I/O error, embedding-API failure, etc.), the helper catches it, logs a warning that names the phase (with `exc_info=True`), and returns an empty string; the phase handshake then proceeds without the `## Relevant memory` section. The rule exists because retrieval quality is best-effort and never load-bearing -- the orchestrator can complete its phase from the directive + task + artifacts alone. A blocking handshake on retrieval failure would couple workflow correctness to optional infrastructure (the embedding provider, the LanceDB vector index). Leon accepted this fail-soft design when the warning-log path was wired.
