---
title: koan routes all agent model_settings through one build_model_settings seam
  and sets no explicit temperature, relying on provider defaults
type: decision
created: '2026-06-20T11:24:27Z'
modified: '2026-06-20T11:24:27Z'
related:
- 0171-model-thinking-is-a-portable-koan-thinkingmode.md
- 0228-koan-retries-transient-provider-errors-at-the.md
---

After an Anthropic reflect call failed with a 400 ("temperature may only be set to 1 when thinking is enabled or in adaptive mode") on 2026-06-20, Leon decided that both koan's memory LLM agents (`koan/memory/llm.py:generate`, `koan/memory/retrieval/reflect.py:_build_agent`) and the regular agents (`koan/agents/pydantic_ai.py`) must build their pydantic-ai `model_settings` through the single `koan/agents/adapter.py:build_model_settings(spec)` function, and that no koan code sets an explicit `temperature` -- inference temperature is left entirely to the provider/PydanticAI default. `build_model_settings` is a pure pass-through over `ModelSpec.settings` (thinking and caching are baked in earlier at flatten time), so it emits no temperature and never conflicts with thinking.

Rationale: sane defaults over configurability (Leon stated he does not care about temperature configurability), and one shared seam removes the per-call edge cases that produced the bug. Alternatives rejected: (1) adding a new dedicated "map thinking effort to temperature" helper -- unnecessary because build_model_settings already exists, is already the regular-agent seam, and already emits no temperature; (2) keeping temperature 0.0 only when thinking is disabled (a conditional) -- rejected because the conditional reintroduces exactly the thinking-vs-temperature coupling that caused the failure. The prior memory behavior of forcing temperature 0.0 for deterministic summaries was deliberately given up; memory summaries now use the provider default temperature.
