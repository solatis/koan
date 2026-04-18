---
title: Per-phase summary capture rides on orchestrator's last prose turn before first
  koan_yield
type: decision
created: '2026-04-17T09:37:08Z'
modified: '2026-04-17T09:37:08Z'
---

This entry documents the per-phase summary capture mechanism for koan's mechanical RAG injection pipeline. On 2026-04-17, user decided that the orchestrator's last assistant text immediately preceding the first `koan_yield` of each phase is captured as that phase's summary, written into `Run.phase_summaries[phase]` via the `phase_summary_captured` event. Subsequent yields within the same phase do not overwrite. Rationale: the orchestrator already writes prose summaries informally before yielding at phase boundaries, so the contract piggybacks on existing behavior with zero new tool calls. Alternative rejected: a dedicated `koan_phase_summary` MCP tool that would have produced cleaner audit artifacts but would have forced the summary to render BOTH as a tool call and as chat text, duplicating the rendering surface and complicating the conversation entry types. Known limitation: runner buffering may deliver the tool call before the final text deltas have been folded into the projection; user accepted this risk and post-mortem identified that captures shorter than 50 characters are logged as warnings via `_extract_last_orchestrator_text` in `koan/web/mcp_endpoint.py`. Implementation surfaced during the 2026-04-17 plan workflow that wired RAG injection into phase transitions.
