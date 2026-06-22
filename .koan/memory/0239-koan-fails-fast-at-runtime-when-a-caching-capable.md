---
title: koan fails fast at runtime when a caching-capable route shows zero cache reads
  at volume (cache_guard.check_cache_effectiveness)
type: decision
created: '2026-06-22T05:25:51Z'
modified: '2026-06-22T05:25:51Z'
related:
- 0238-prompt-caching-capability-is-keyed-on-connection.md
- 0159-prompt-caching-is-required-configured-per.md
- 0161-cache-prefix-stability-is-load-bearing-a-byte.md
- 0228-koan-retries-transient-provider-errors-at-the.md
---

koan added a runtime fail-fast guard for prompt-cache effectiveness in koan/agents/cache_guard.py (check_cache_effectiveness), wired into the multi-turn loop in koan/agents/loop.py (run_agent_loop). The loop accumulates input_tokens, cache_read_tokens, and request counts across turns and, at each turn boundary, raises AgentError(code="prompt_cache_ineffective") when a caching-capable route has re-sent substantial input yet produced zero cache reads. The scope predicate cache_read_expected (koan/agents/model_catalog.py) covers all four first-class routes -- Anthropic and Bedrock-Claude (koan-managed explicit caching) plus Google and OpenAI (automatic server-side caching) -- because all four report cache_read through pydantic-ai's RequestUsage; OpenRouter, Voyage, and Bedrock-Nova are excluded. The trip is absolute-zero (cache_read_tokens exactly 0), gated by the named thresholds CACHE_GUARD_MIN_REQUESTS (2 model requests) and CACHE_GUARD_MIN_INPUT_TOKENS (50000 tokens), so a single-request scout or a sub-4096-token Haiku prefix that legitimately misses does not fire. The guard runs at the turn boundary OUTSIDE the ModelRequestNode retry wrapper, so the AgentError is an unexpected/fail-fast fault rather than a transient retry and propagates through PydanticAIAgent.run unchanged. Leon set the policy: a runtime usage assertion that raises, because a silent cache miss re-sends full input at full price and burns budget fast, which he classified as a logic error worth an explicit check. Alternatives rejected: a build-time structural assertion (it cannot observe whether caching actually took effect, only that settings were emitted); warn-only logging (Leon wanted fail-fast); and policing only the explicit-control routes (he chose all caching-capable routes). The guard is cumulative and absolute-zero by design: it targets the "caching never started" failure class and disarms permanently once any cache read is observed, so it does not detect a mid-run regression after caching has worked at least once.
