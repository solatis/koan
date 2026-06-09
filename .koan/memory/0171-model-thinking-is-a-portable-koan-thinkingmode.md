---
title: Model thinking is a portable koan ThinkingMode translated to provider settings
  by adapter.map_thinking
type: context
created: '2026-06-05T01:50:20Z'
modified: '2026-06-05T01:50:20Z'
related:
- 0155-provider-config-reshaped-to-modelspec.md
- 0159-prompt-caching-is-required-configured-per.md
---

koan expresses model reasoning effort as one portable `ThinkingMode` (`disabled`/`low`/`medium`/`high`/`xhigh`/`max`, defined in `koan/types.py`) carried on each `ModelSpec`, and `koan/agents/adapter.py:map_thinking(provider, mode)` translates it into that provider's own `model_settings`. The mappings differ by provider: Google and Anthropic take a thinking-token budget (`google_thinking_config` budget / `anthropic_thinking` `{type: enabled, budget_tokens}`), OpenAI takes the coarse `openai_reasoning_effort` knob (low/medium/high), and Bedrock is a deliberate no-op because thinking there is selected by the underlying model profile rather than a portable koan-level knob. `build_model_settings` merges `ModelSpec.settings` with this thinking mapping and the caching settings into the dict handed to pydantic-ai. Because thinking lives on the per-tier `ModelSpec`, the strong/standard/cheap tiers already differentiate reasoning effort by cognitive role without a separate role-to-effort table. This matters because a single koan `ThinkingMode` means different things to each provider: it is set once on the ModelSpec and resolved per-provider in `map_thinking`, not configured at call sites.
