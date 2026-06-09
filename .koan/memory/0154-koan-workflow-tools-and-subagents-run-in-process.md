---
title: koan workflow tools and subagents run in-process (FunctionToolset + asyncio
  tasks); the HTTP MCP transport is removed
type: decision
created: '2026-06-04T14:11:54Z'
modified: '2026-06-04T14:11:54Z'
related:
- 0153-koan-owns-the-multi-turn-agent-loop-in-process.md
- 0006-directory-as-contract-taskjson-over-cli-flags-for.md
- 0068-blocking-mcp-tool-handlers-that-park-on-per-run.md
---

Because koan owns the agent loop, the koan workflow tools are a PydanticAI `FunctionToolset` called directly inside the loop, and subagents (executor and scout) run as in-process asyncio tasks -- scouts still gated by the existing concurrency semaphore -- rather than as spawned CLI processes reached over a network endpoint. The HTTP MCP server (`/mcp`), the `AgentResolutionMiddleware` that derived agent identity from the request URL, and the Future-over-MCP round-trip that backed blocking interactions are all removed; tool dispatch is now a direct in-process function call. The `task.json` directory contract for subagents is retained, and blocking interactions (`koan_ask_question`, `koan_memory_propose`, and the hand-back) stay as in-process blocking awaits. Leon accepted the loss of subagent process isolation: it is contained by task-level exception handling, where an `AgentError` raised inside a subagent task surfaces to the parent as a failed `SubagentResult` rather than crashing it. Alternative rejected: keeping the HTTP MCP transport for process isolation and codex/gemini parity, which would forfeit the in-process loop's caching and history ownership.
