---
title: "TextOutput(_reject_text) kills streaming \u2014 the PydanticAI trap pattern\
  \ is wrong when terminal text output is desired"
type: lesson
created: '2026-07-04T15:21:58Z'
modified: '2026-07-04T15:21:58Z'
related:
- 0078-pydantic-ai-integration-traps-in-koan-agent-loops.md
- 0063-koanreflect-synthesis-tool-single-conversation.md
---

The `koan_reflect` synthesis tool in `koan/memory/retrieval/reflect.py` — the `_build_agent` function set `output_type=TextOutput(_reject_text)`, where `_reject_text` raises `ModelRetry("Do not produce text output. Call the done tool instead.")` on every text emission. This pattern, prescribed by the PydanticAI integration traps lesson for forcing structured tool-call output, was actively harmful in the reflect agent: the `text` → `reflect_delta` → `result.answer` streaming pipeline was fully wired end to end (backend fold through the `ReflectCard` streaming cursor in `frontend/src/components/molecules/KoanToolCard.tsx`) but structurally dead, because the only text the model could emit was text that got rejected and retried. Every rejected text emission burned a model-request turn against `MAX_ITERATIONS = 10` and briefly polluted `result.answer` with deltas of rejected text before the final `tool_completed` merge overwrote it.

Root cause: the reflect agent was originally designed with `done(answer, memory_ids)` — prose inside a JSON tool argument — which made `TextOutput(_reject_text)` necessary to prevent the model from terminating with prose instead of calling the `done` tool. When the design changed to terminal-text briefing (the model's final plain-text output IS the briefing, ending the loop via PydanticAI's native End condition), the reject pattern became the bottleneck: it was preventing the very text output that was now the desired termination.

Prevention: before applying `TextOutput(_reject_text)`, verify whether the agent's desired termination is a tool call (use the pattern) or streaming terminal text (do not use the pattern). The pattern is correct when structured output through a tool call is required; it is wrong when streaming prose is the intended output channel.
