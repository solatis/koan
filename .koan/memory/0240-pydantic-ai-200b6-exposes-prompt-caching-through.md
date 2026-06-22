---
title: pydantic-ai 2.0.0b6 exposes prompt caching through per-model-class settings
  keys (anthropic_cache* vs bedrock_cache*), with no path for OpenRouter
type: context
created: '2026-06-22T05:26:06Z'
modified: '2026-06-22T05:26:06Z'
related:
- 0238-prompt-caching-capability-is-keyed-on-connection.md
- 0239-koan-fails-fast-at-runtime-when-a-caching-capable.md
- 0164-plan-built-on-the-pydanticai-v2-beta-assumed-its.md
- 0078-pydantic-ai-integration-traps-in-koan-agent-loops.md
---

In pydantic-ai 2.0.0b6, prompt caching is configured by model-class-specific model_settings keys whose names differ per class -- there is no single cross-provider caching switch, and the model profiles expose no prompt-caching capability flag (so koan owns that knowledge in koan/agents/model_catalog.py). AnthropicModel reads anthropic_cache (a top-level auto-advancing breakpoint over the message prefix that moves forward as the conversation grows, counts as 1 of Anthropic's 4 cache slots, auto-trims excess, and is mutually exclusive with anthropic_cache_messages), plus anthropic_cache_instructions (system prompt) and anthropic_cache_tool_definitions (tool schemas). BedrockConverseModel reads different keys -- bedrock_cache_messages, bedrock_cache_instructions, bedrock_cache_tool_definitions -- emitting cachePoint blocks, and it folds cache tokens into input_tokens while still reporting cache_read separately. OpenRouterModel extends OpenAIChatModel, has no caching path, and the OpenAI base filters out CachePoint, so there is no supported way to drive OpenRouter prompt caching through pydantic-ai. Google and OpenAI cache automatically server-side and report cache reads via RequestUsage.extract (google's cached_content_token_count and openai's cached_tokens both map to cache_read_tokens). This matters because any koan change to caching must emit the transport-correct keys; passing Anthropic keys to a Bedrock or OpenRouter model silently caches nothing.
