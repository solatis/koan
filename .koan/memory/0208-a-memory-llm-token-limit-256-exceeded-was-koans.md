---
title: A memory-LLM "token limit (256) exceeded" was koan's own max_tokens output
  cap, not the LM Studio context window; a local reasoning model burned the budget
  on thinking tokens
type: lesson
created: '2026-06-11T23:28:38Z'
modified: '2026-06-11T23:28:38Z'
related:
- 0207-koan-hardcodes-lm-studios-context-window-to-a.md
- 0184-local-ai-lm-studio-support-keyless-openai.md
---

koan's memory subsystem (`koan/memory/retrieval/rag.py`, `koan/memory/llm.py`) failed when its `memory_llm` binding pointed at a local LM Studio reasoning model (`qwen/qwen3.6-35b-a3b`): per-phase memory retrieval died with `pydantic_ai.exceptions.UnexpectedModelBehavior: Model token limit (256) exceeded before any response was generated`. Leon reported it as a context-window problem ("we set LM Studio's context window to 256k but it isn't taking effect") because the log line showed `max_tokens=256`.

Root cause: that `256` is koan's own OUTPUT token cap, hardcoded as `max_tokens=256` in `rag.py:generate_queries` (the memory RAG search-query generator) and threaded through `memory/llm.py:generate` into the chat completion. It has nothing to do with the context window; the coincidence of `256` (output cap) versus `256k` (the context window Leon had set) drove the misdiagnosis. `qwen/qwen3.6-35b-a3b` is a reasoning model -- it spends output tokens on hidden thinking before emitting answer text, so the 256-token budget was exhausted mid-reasoning ("exceeded before any response was generated"). `adapter.map_thinking` is a hardcoded no-op for the `lmstudio` provider, so koan has no lever to suppress that reasoning; the only available fix was to enlarge the budget, raised to `max_tokens=2048` (the same order as the 2500 cap already used by `memory/summarize.py`). The misdiagnosis had even propagated into a curated memory decision, which recorded the observed "256" as "LM Studio's own server-side default" for context.

Prevention: `max_tokens` (the per-request OUTPUT ceiling) and the context window (the input budget) are different quantities; an "UnexpectedModelBehavior: token limit exceeded before any response was generated" is an output-cap symptom, not a context problem -- read the code path that emits the number before attributing it. When a memory-LLM or other mechanical call targets a local reasoning model, size `max_tokens` to cover thinking tokens plus the intended output, because koan cannot disable reasoning on the `lmstudio` path.
