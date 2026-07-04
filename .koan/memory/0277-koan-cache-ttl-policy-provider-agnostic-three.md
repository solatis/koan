---
title: 'koan cache TTL policy: provider-agnostic three-breakpoint model with stable
  context = long (1h), tail = short (5m), gated to long-lived roles'
type: decision
created: '2026-07-03T08:51:03Z'
modified: '2026-07-03T08:51:03Z'
related:
- 0238-prompt-caching-capability-is-keyed-on-connection.md
- 0240-pydantic-ai-200b6-exposes-prompt-caching-through.md
- 0161-cache-prefix-stability-is-load-bearing-a-byte.md
- 0159-prompt-caching-is-required-configured-per.md
---

koan's prompt-cache TTL emission (`koan/agents/adapter.py` `_caching_settings`, `koan/agents/registry.py` `build_resolved_model`) was reworked from a single uniform TTL per cache tier into a per-breakpoint split reasoned in terms of three provider-agnostic semantic breakpoints: `cache_system_prompt` (the system prompt, which by design bundles the tool definitions -- both are stable), `cache_artifacts` (placed after the injected handoff artifacts + the artifact listing), and `cache_tail` (the growing turn-by-turn conversation). The stable prefix (`cache_system_prompt` + `cache_artifacts`) carries the LONG TTL and the churny `cache_tail` carries the SHORT TTL. Leon directed the design. Rationale: the conversation churns every turn, so a long TTL on the tail wastes cache-write cost, while the stable prefix is long-lived and benefits from the long TTL; reasoning in semantic breakpoints rather than provider-specific `anthropic_cache*`/`bedrock_cache*` keys keeps the concept reusable for a future Gemini adapter. A role gate (`cache_tier_for_role` in `koan/types.py`) restricts the split to the long-lived orchestrator and executor; scouts and reviewers are single-shot, never wait between turns, and stay all-short. Anthropic and Bedrock get the identical split because both are Claude-family and both honor per-breakpoint TTL. "60m" maps to pydantic-ai's existing `'1h'` literal and "5m" to `'5m'` -- pydantic-ai accepts only `Literal['5m','1h']`, so no TTL value changed; only the per-breakpoint assignment changed. No `CachingPolicy` schema field was added; the policy stays in the adapter/registry mapping keyed on `CachingPolicy.mode`. Alternatives rejected: keeping the uniform single-tier provider-keyed emission (cannot give artifacts a long TTL while the tail stays short); applying the split to all roles regardless of lifetime (wasteful for short-lived agents); introducing a literal `'60m'` (not expressible in the transport).
