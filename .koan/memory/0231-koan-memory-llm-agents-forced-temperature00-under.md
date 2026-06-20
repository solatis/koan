---
title: koan memory LLM agents forced temperature=0.0 under baked Anthropic thinking,
  causing a 400; root cause was bypassing the build_model_settings seam
type: lesson
created: '2026-06-20T11:24:21Z'
modified: '2026-06-20T11:24:21Z'
related:
- 0078-pydantic-ai-integration-traps-in-koan-agent-loops.md
- 0208-a-memory-llm-token-limit-256-exceeded-was-koans.md
- 0228-koan-retries-transient-provider-errors-at-the.md
- 0171-model-thinking-is-a-portable-koan-thinkingmode.md
---

koan's memory LLM agents -- `koan/memory/retrieval/reflect.py:_build_agent` (the koan_reflect synthesis loop) and `koan/memory/llm.py:generate` (summaries / query decomposition) -- constructed their pydantic-ai `Agent` with `model_settings={**model.settings, "temperature": 0.0}`. When the bound model was Anthropic with extended/adaptive thinking baked into `ModelSpec.settings` (e.g. `anthropic_thinking: {type: adaptive}`), a reflect call returned HTTP 400 `invalid_request_error`: "temperature may only be set to 1 when thinking is enabled or in adaptive mode" (observed 2026-06-20 against claude-sonnet-4-6). The failure showed up in logs as `AgentError ... for orchestrator: PydanticAIAgent run failed` rather than as a memory error, because koan_reflect runs as a tool inside the orchestrator's run and the inner provider 400 bubbled up through the orchestrator's PydanticAIAgent. Because the 400 is a deterministic invalid_request, koan's transient-error retry classifier correctly did not retry it.

Root cause: the memory constructors built `model_settings` independently and force-set a temperature, instead of using the shared `koan/agents/adapter.py:build_model_settings(spec)` seam that the regular agent path (`koan/agents/pydantic_ai.py`) already uses. That seam is a pure pass-through over `ModelSpec.settings` and never sets a temperature, so the regular agents were immune; only the divergent memory path collided with Anthropic's thinking/temperature rule.

Prevention: every pydantic-ai `Agent` koan constructs derives its `model_settings` from `build_model_settings(spec)` and sets no explicit temperature, leaving it to the provider/PydanticAI default. Leon flagged the expectation gap that PydanticAI does not auto-reconcile temperature with thinking, so koan must avoid handing it a conflicting temperature in the first place.
