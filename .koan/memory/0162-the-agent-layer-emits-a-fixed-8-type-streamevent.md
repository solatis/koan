---
title: The agent layer emits a fixed 8-type StreamEvent vocabulary consumed unchanged
  by subagent fan-out and both fold systems
type: context
created: '2026-06-04T14:16:42Z'
modified: '2026-06-04T14:16:42Z'
related:
- 0007-dual-fold-system-audit-fold-per-subagent-disk-vs.md
- 0153-koan-owns-the-multi-turn-agent-loop-in-process.md
---

koan's agent layer emits events in a fixed 8-type `StreamEvent` vocabulary (`koan/agents/events.py`): `token_delta`, `turn_complete`, `thinking`, `assistant_text`, `tool_start`, `tool_input_delta`, `tool_stop`, and `tool_result`. This vocabulary is the contract between the agent loop and everything downstream: `spawn_subagent`'s event fan-out and both fold systems -- the per-subagent audit fold and the workflow projection fold -- consume it unchanged. That makes it the highest-risk seam in the agent layer: adding or renaming an event type is not a local change, it ripples into both folds and the projection. Specific fields ride specific events: `turn_complete` carries a `usage` field (a PydanticAI `RequestUsage`) for per-request token accounting; `tool_result` carries `metrics` (tool-family-specific) and `attachments` (extracted from result content blocks). The `KOAN_MCP_TOOLS` frozenset in the same module is how the projection fold tells a koan workflow-tool call apart from a built-in tool call. This matters because the breadth of consumers makes event-type changes expensive and easy to underestimate.
