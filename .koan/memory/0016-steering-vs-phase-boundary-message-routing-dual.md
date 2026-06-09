---
title: 'Steering vs phase-boundary message routing: dual-queue design'
type: decision
created: '2026-04-16T08:37:51Z'
modified: '2026-06-04T14:26:37Z'
related:
- 0158-koanyield-removed-the-agent-loops-terminal-text.md
- 0161-cache-prefix-stability-is-load-bearing-a-byte.md
---

koan routes a user's chat message to one of two destinations depending on whether the orchestrator loop is currently parked at a hand-back; the chat endpoint decides by inspecting whether a loop-owned `yield_future` is set. A message that arrives while the loop is parked at its terminal-text hand-back is a phase-boundary reply: it resolves the `yield_future`, and the buffered user messages are drained and assembled into the next turn's prompt (`assemble_resume_prompt` in `koan/agents/loop.py`). A message that arrives while the orchestrator is mid-turn is steering: it is queued and, after the current `CallToolsNode` completes, drained by `drain_and_render_steering` and injected via `agent_run.enqueue()` as a user-prompt part before the next model request -- never spliced between a tool call and its result. koan deliberately keeps the two paths independent so a message is delivered exactly once. This shape replaced an earlier design in which a phase-boundary reply returned as the `koan_yield` tool result and steering was appended to the next MCP tool response; both delivery mechanisms changed when the loop moved in-process and `koan_yield` was removed, but the route-by-whether-the-loop-is-parked distinction is unchanged.
