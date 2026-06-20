---
title: Token/context economy is a first-class design driver in koan since the June
  2026 agent-layer migration
type: context
created: '2026-06-20T00:15:02Z'
modified: '2026-06-20T00:15:02Z'
related:
- 0152-koans-agent-layer-is-one-native-pydanticai.md
- 0153-koan-owns-the-multi-turn-agent-loop-in-process.md
- 0157-tool-vocabulary-is-restricted-at-toolset.md
- 0161-cache-prefix-stability-is-load-bearing.md
- 0173-three-class-tool-trust-taxonomy-untrusted-built.md
---

koan treats token and context-window economy as a primary design constraint -- weighed explicitly when adding a prompt, a tool, a phase, or a projection field, rather than as an afterthought. Leon established this posture with the June 2026 agent-layer migration: koan moved off the Claude Agent SDK and the codex/gemini provider CLIs onto a single in-process PydanticAI loop (`koan/agents/loop.py:run_agent_loop`) speaking direct provider APIs. That move both exposed economy and enabled it -- owning the loop surfaced true per-turn token usage and cost (PydanticAI RequestUsage/RunUsage plus genai-prices pricing), which an earlier character-length token approximation had hidden, and it handed koan the seams to optimize.

The priority is visible across the agent layer as concrete, load-bearing constraints rather than aspirations: cross-turn prompt caching is required and configured per provider; cache-prefix stability is load-bearing, which is why toolsets are composed once per (role, phase) and never per step (a step-granular toolset would invalidate the tool-definition cache at every step boundary); context files (AGENTS.md/CLAUDE.md) are injected just-in-time on first tool-touch of a subtree instead of preloaded; oversized untrusted tool output (read/grep/glob/bash) is rejected rather than truncated so it never lands in the transcript; the strong/standard/cheap model tiering routes narrow work such as scouting to cheap models; and the header surfaces live cost and context-window-percent gauges so the operator sees consumption as it accrues.

This matters because koan's recent direction is to spend tokens deliberately: a change that adds tokens to every turn -- a longer system prompt, a new always-on tool, a verbose tool return, a new field carried in early history -- works against both the cost priority and the cache prefix, and is exactly the kind of tradeoff koan now weighs before adopting.
