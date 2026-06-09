---
title: Built-in agent tools reimplemented as native koan function tools; web search/fetch
  are local (ddgs+httpx), not provider-native
type: decision
created: '2026-06-04T14:12:13Z'
modified: '2026-06-04T14:12:13Z'
related:
- 0153-koan-owns-the-multi-turn-agent-loop-in-process.md
- 0007-dual-fold-system-audit-fold-per-subagent-disk-vs.md
---

koan supplies its agents' built-in tools -- read, write, edit, glob, grep, bash, and web search/fetch -- as its own PydanticAI function tools (`koan/tools/builtin_tools.py`), because owning the agent loop means koan must provide the tooling a provider SDK previously gave for free. Web search and fetch are deliberately local, built on the `ddgs` DuckDuckGo client and `httpx`. Leon's rationale: a local web tool is portable across all four providers (AWS Bedrock has no native web search), and because it runs as an ordinary koan function tool its results flow through the same `StreamEvent` and projection path as the other built-ins. Alternative rejected: a provider-native web builtin, which would bypass koan's event and projection path and differ per provider. bash sandboxing was not added -- the existing bash posture is kept. Built-in tool output is shaped to match koan's metrics-parser contract so the projection fold reads per-call metrics consistently.
