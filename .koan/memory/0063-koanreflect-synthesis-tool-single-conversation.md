---
title: koan_reflect synthesis tool -- single-conversation LLM tool-calling loop with
  driver-resolved citations
type: decision
created: '2026-04-20T08:43:52Z'
modified: '2026-07-01T01:22:39Z'
related:
- 0020-memory-retrieval-static-directive-mechanical.md
---

This entry documents the architecture of `koan_reflect`, an agent-invoked retrieval tool in the koan memory system implemented in `koan/memory/retrieval/reflect.py`. Leon approved the implementation on 2026-04-20 as a single-conversation LLM tool-calling loop. The LLM itself drives the loop: it plans 3-5 query angles, calls an internal `search` tool as many times as it needs, reviews accumulated evidence, and calls an internal `done` tool with the final briefing. The `done` tool accepts `answer: str` and `memory_ids: list[int]`; the driver validates each id against the set of entries returned by `search` calls during the loop, drops unmatched ids with a log entry, and resolves surviving ids to `{id, title}` pairs via the retrieved-set dict. The MCP response shape is `{answer, citations, iterations}`.

Leon rejected four alternatives on 2026-04-20: (1) separately orchestrated single-turn prompts for query planning, sufficiency evaluation, and synthesis -- this moves control flow outside the LLM and prevents adaptive search decisions; (2) cheap-tier model per the original koan spec -- Leon agreed multi-turn tool-calling reliability degrades sharply on small models that echo the full question as a single query and produce malformed tool calls; (3) `forced=true` best-effort partial briefing on iteration cap -- Leon specified fail-fast with `ToolError("iteration_cap_exceeded")` at `MAX_ITERATIONS=10`; (4) a sibling Gemini wrapper module for the reflect client separate from the summarization client.

The model-resolution path has changed twice since the original implementation. Originally `reflect.py` held module-local `_api_key()` / `_model()` helpers and a `KOAN_REFLECT_MODEL` constant defaulting to `gemini-2.5-pro`, constructing its own strong-tier client independently of `koan/memory/llm.py` (the cheap-tier summarization path). On 2026-06-12 the module-global model/credential resolution was removed and `koan_reflect` began receiving a resolved `ModelSpec` from the per-run `MemoryModels` bundle's `reflect_llm` field (see the memory-subsystem model-resolution decision). On 2026-07-01 the dedicated `reflect_llm` field was removed; `koan_reflect` now resolves its model from the standard tier through the same frozen-model discovery as execution agents and scouts (cheap for summarization, standard for reflection), eliminating the module-local model construction entirely. The loop architecture (single conversation, internal `search`/`done` tools, driver-resolved citations) is unchanged across these model-resolution changes.
