---
title: 'Mechanical RAG injection is fail-soft: log warning, never block phase handshake'
type: procedure
created: '2026-04-17T09:38:05Z'
modified: '2026-04-27T09:01:21Z'
---

This entry records a behavioral rule for koan's mechanical memory injection pipeline at the orchestrator's phase handshake. On 2026-04-17, the team established the procedure: when `_compute_memory_injection` in `koan/web/mcp_endpoint.py` raises any exception (missing `VOYAGE_API_KEY`, empty `.koan/memory/`, LanceDB I/O error, embedding API failure, etc.), the helper catches the exception, logs it at `warning` level via `log.warning("mechanical memory injection failed for phase %r ...", exc_info=True)`, and returns an empty injection block. The phase handshake proceeds without the `## Relevant memory` section. The rule exists because retrieval quality is best-effort and never load-bearing -- the orchestrator can complete its phase from the directive + task + artifacts alone. A blocking handshake on retrieval failure would couple workflow correctness to optional infrastructure. Procedure surfaced during 2026-04-17 plan-spec when the user accepted the fail-soft design decision and the executor wired warning log lines per the plan.
