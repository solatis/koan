---
title: docs/memory-system.md described an unimplemented summary.md load step in the
  injection pipeline
type: lesson
created: '2026-04-17T09:38:19Z'
modified: '2026-04-17T09:38:19Z'
related:
- 0032-plan-review-produced-unverified-critical-finding.md
---

This entry records a documentation-versus-code drift in koan's memory system. On 2026-04-17, plan-review discovered that `docs/memory-system.md` described a 5-step mechanical injection pipeline whose first step was "Load project summary -- summary.md is loaded in full ... runs only at intake" -- a step that was never wired into the orchestrator's phase handshake. The `_step_phase_handshake` code path in `koan/web/mcp_endpoint.py` had no summary.md load at any point; the injection helper composed the anchor from task + artifacts + prior phase summary alone. Root cause: the design spec was authored aspirationally during the memory system design phase and never reconciled when the partial wiring landed. Plan-review caught the drift only because the reviewer cross-checked the doc claim against the actual code path, which is not a routine review move. Correction applied during the 2026-04-17 RAG-wiring workflow: the doc was rewritten to describe a 4-step pipeline (drop the summary.md load) and an "Implementation mapping" subsection was appended pinning the doc to specific file/function names. Adding the summary.md load is left to a future workflow if the user wants it.
