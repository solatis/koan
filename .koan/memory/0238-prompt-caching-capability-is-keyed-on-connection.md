---
title: Prompt-caching capability is keyed on (connection transport, model family),
  and one CachingPolicy is translated to per-transport keys (anthropic_cache* vs bedrock_cache*)
type: decision
created: '2026-06-22T05:25:29Z'
modified: '2026-06-22T05:25:29Z'
related:
- 0159-prompt-caching-is-required-configured-per.md
- 0190-koan-resolves-model-capabilities-by-wrapping.md
- 0161-cache-prefix-stability-is-load-bearing-a-byte.md
---

koan resolves prompt-caching capability on the pair (connection transport, model family) rather than the raw connection-provider string, in koan/agents/model_catalog.py (supports_prompt_caching) and koan/agents/adapter.py (_caching_settings). supports_prompt_caching returns True only when the transport is anthropic or bedrock AND parse_model_id(model).family is a Claude family (claude-opus / claude-sonnet / claude-haiku); parse_model_id strips the Bedrock "anthropic." vendor prefix so "anthropic.claude-opus-4-0" resolves to the Claude family. This corrected an earlier design that keyed caching on the provider alone (the frozenset {"anthropic"}), which both excluded Bedrock-hosted Claude and conflated the model capability with the transport mechanism. Bedrock-hosted Claude now caches; Bedrock-hosted Amazon Nova is family-scoped out. Because capability and mechanism are different axes, the adapter translates one koan CachingPolicy into different pydantic-ai keys per transport: Anthropic emits anthropic_cache + anthropic_cache_instructions + anthropic_cache_tool_definitions; Bedrock emits bedrock_cache_messages + bedrock_cache_instructions + bedrock_cache_tool_definitions. The message-prefix breakpoint (anthropic_cache / bedrock_cache_messages) was previously absent, so only the system-prompt and tool-definition breakpoints were cached and the fast-growing message history was re-sent uncached every turn. OpenRouter was kept out of scope because pydantic-ai's OpenRouterModel has no caching path. Leon directed the (transport, family) framing and the short cache tier (5m) when a provider offers multiple TTLs.
