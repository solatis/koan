---
title: koan owns the multi-turn agent loop in-process (run_agent_loop), trading OS
  crash isolation for caching, cost accounting, and history ownership
type: decision
created: '2026-06-04T14:11:43Z'
modified: '2026-06-04T14:11:43Z'
related:
- 0152-koans-agent-layer-is-one-native-pydanticai.md
- 0001-persistent-orchestrator-over-per-phase-cli.md
- 0007-dual-fold-system-audit-fold-per-subagent-disk-vs.md
---

koan drives its own multi-turn agent loop in `koan/agents/loop.py:run_agent_loop`: each turn is one `pydantic_ai` `agent.iter()` run, and koan owns the conversation history threaded from one turn to the next, instead of delegating the loop to a provider SDK or CLI. Leon treats loop ownership as the linchpin of the agent design, because owning the loop and the message history is what makes five things possible: prompt caching across turns; real token-usage and cost accounting (PydanticAI `RequestUsage`/`RunUsage` for tokens and `genai-prices` for price, with `context_window` carried on each `ModelSpec` since PydanticAI does not expose a model's maximum window); just-in-time context-file injection; explicit history ownership; and a seam for future interrupts, compaction, and context-surgery. The accepted cost is loss of OS-level crash isolation, since the loop and the subagents it spawns run in-process. Alternative rejected: letting a provider SDK or CLI own the loop -- koan could then neither cache deterministically, account for true cost, nor own the history. This loop-ownership choice is the anchor the rest of the agent-layer decisions depend on; the real-usage accounting it enables replaced an earlier character-length token approximation.
