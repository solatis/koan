---
title: koan sets an explicit clamped max_tokens output budget (default 32768) at the
  model-flatten seam, with a koan-owned per-model output-cap table
type: decision
created: '2026-06-30T02:17:22Z'
modified: '2026-06-30T02:17:22Z'
related:
- 0190-koan-resolves-model-capabilities-by-wrapping.md
- 0208-a-memory-llm-token-limit-256-exceeded-was-koans.md
- 0230-tokencontext-economy-is-a-first-class-design.md
- 0232-koan-routes-all-agent-modelsettings-through-one.md
- 0078-pydantic-ai-integration-traps-in-koan-agent-loops.md
---

koan's model-settings flatten step (`build_resolved_model` in `koan/agents/registry.py`) bakes an explicit `max_tokens` output budget into every resolved `ModelSpec.settings`. The value comes from the module constant `DEFAULT_MAX_OUTPUT_TOKENS = 32768` in `koan/agents/model_catalog.py`, clamped per model to `min(32768, cap)` by `max_output_tokens_for(provider, model)`. The caps live in a koan-owned table, `MODEL_MAX_OUTPUT_TOKENS`, that lists only models whose hard output ceiling sits below 32768 -- for example claude-3-5-haiku-latest (8192), gpt-4o and gpt-4o-mini (16384), claude-opus-4-0 (32000), and the amazon.nova text models (5120); the table is the source of truth. Every other model, and any uncataloged or dynamic id such as openrouter or ollama-cloud, takes the 32768 default. One bake covers all agent roles and the memory LLMs because they share the `build_model_settings(spec)` seam; the embedding ModelSpec is constructed separately with empty settings and is intentionally excluded.

Leon decided this on 2026-06-30 after the orchestrator crashed on a complex turn where, with `max_tokens` unset, pydantic-ai applied its hardcoded Anthropic fallback of 4096 and adaptive thinking consumed the whole budget before any response text. The goal is a uniformly high OUTPUT floor so the output cap is never the limiter while context-window headroom remains; 32768 is accepted as both floor and ceiling for now. This makes koan track per-model OUTPUT caps even though it deliberately does NOT track per-model input/context windows (that catalog data was removed in an earlier hard cutover): koan must send a valid max_tokens itself and a too-high value is rejected by the provider, whereas the input limit is enforced by the provider alone.

Alternatives rejected: setting max_tokens only for Anthropic, the lone provider whose unset default is broken (the others omit it and use the model default) -- rejected because Leon wanted the floor uniform across all providers; a blanket 32768 with no clamp -- rejected because Anthropic, OpenAI, and Bedrock return HTTP 400 when max_tokens exceeds the model cap, so low-cap models would fail outright; per-preset/slot/env configurability -- rejected for a single constant, sane defaults over configurability; and scaling the value by thinking tier -- explicitly deferred as unrelated for now.
