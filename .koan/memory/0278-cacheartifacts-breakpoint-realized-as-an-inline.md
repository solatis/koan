---
title: cache_artifacts breakpoint realized as an inline pydantic-ai CachePoint attached
  once at phase entry to the last preseeded artifact/listing message
type: decision
created: '2026-07-03T08:51:03Z'
modified: '2026-07-03T08:51:03Z'
related:
- 0161-cache-prefix-stability-is-load-bearing-a-byte.md
- 0257-phase-handovers-are-injected-immutable-artifacts.md
- 0240-pydantic-ai-200b6-exposes-prompt-caching-through.md
---

In koan's cache-TTL policy, the `cache_artifacts` semantic breakpoint is realized by attaching a `pydantic_ai.messages.CachePoint(ttl='1h')` to the last artifact/listing message the injection layer appended, rather than by relying on the auto-advancing tail breakpoint (`anthropic_cache` / `bedrock_cache_messages`). Rationale: the auto-advancing breakpoint tracks the growing tail (not the artifact region) and can carry only one TTL, so it cannot give artifacts a long TTL while the tail stays short. Implementation: `koan/tools/handoff_artifacts.py` `apply_artifact_cache_point(agent, target_index)` is a pure, role-gated (`cache_tier_for_role == "long"`), idempotent helper called from `run_agent_loop` (`koan/agents/loop.py`) after the `preseed_pending_*` calls; the loop computes `target_index` from the pre/post preseed history length and passes a `-1` sentinel on turns where nothing was preseeded. Because the preseeds run only at phase entry (draining `pending_*`, cleared by `reset_phase_context`), the CachePoint is baked once into the persisted artifact `ModelRequest` and rides forward at the fixed artifact boundary via pydantic-ai's `all_messages()` on every later turn. Empty-artifact case: when neither preseed appended a message the helper is a no-op and no `cache_artifacts` breakpoint is emitted (the system+tools settings-key breakpoints still cover the stable prefix). The CachePoint is attached by extending the existing message's `UserPromptPart.content` to `[text, CachePoint]`, not as a bare CachePoint-only message, because both Anthropic and Bedrock reject a CachePoint that is the first content in a user message. Alternatives rejected: a dedicated trailing CachePoint-only `UserPromptPart` (rejected by the transport); relying on the auto-advancing `anthropic_cache` breakpoint alone (tracks the tail, one TTL only).
