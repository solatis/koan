---
title: koan_reflect synthesis tool -- single-conversation LLM tool-calling loop with
  driver-resolved citations
type: decision
created: '2026-04-20T08:43:52Z'
modified: '2026-04-20T08:43:52Z'
related:
- 0020-memory-retrieval-static-directive-mechanical.md
---

This entry documents the architecture of `koan_reflect`, a new agent-invoked retrieval tool in the koan memory system implemented in `koan/memory/retrieval/reflect.py`. On 2026-04-20, Leon approved the implementation of `koan_reflect` as a single-conversation LLM tool-calling loop wrapping Gemini 2.5 Pro function calling. The LLM itself drives the loop: it plans 3-5 query angles, calls an internal `search` tool as many times as it needs, reviews accumulated evidence, and calls an internal `done` tool with the final briefing. The `done` tool accepts `answer: str` and `memory_ids: list[int]`; the driver validates each id against the set of entries returned by `search` calls during the loop, drops unmatched ids with a log entry, and resolves surviving ids to `{id, title}` pairs via the retrieved-set dict. The MCP response shape is `{answer, citations, iterations}`.

Leon rejected four alternatives on 2026-04-20: (1) separately orchestrated single-turn prompts for query planning, sufficiency evaluation, and synthesis -- this moves control flow outside the LLM and prevents adaptive search decisions; (2) cheap-tier model per the original koan spec -- Leon agreed multi-turn tool-calling reliability degrades sharply on small models that echo the full question as a single query and produce malformed tool calls; (3) `forced=true` best-effort partial briefing on iteration cap -- Leon specified fail-fast with `ToolError("iteration_cap_exceeded")` at `MAX_ITERATIONS=10`; (4) sibling Gemini wrapper module -- the thin strong-tier client (using `KOAN_REFLECT_MODEL` defaulting to `gemini-2.5-pro`) lives inside `reflect.py` with module-local `_api_key()` and `_model()` helpers, keeping `koan/memory/llm.py` untouched as the cheap-tier path.
