---
title: Prompt caching is required, configured per provider via a CachingPolicy (Anthropic
  explicit, OpenAI/Gemini automatic, Bedrock CachePoint)
type: decision
created: '2026-06-04T14:14:28Z'
modified: '2026-06-04T14:14:28Z'
related:
- 0153-koan-owns-the-multi-turn-agent-loop-in-process.md
---

koan requires prompt caching on the agent path and configures it per provider through a `CachingPolicy`. A single uniform caching mechanism across providers was rejected because providers expose caching incompatibly: Anthropic needs explicit cache markers (the `anthropic_cache*` flags), OpenAI and Google/Gemini cache automatically server-side, and AWS Bedrock uses `CachePoint` markers with a fallback -- so the policy is per-provider. Caching is one of the primary payoffs of koan owning the agent loop, and it imposes a hard constraint on the loop: the cacheable prefix -- system prompt, tool definitions, and early history -- must stay byte-stable across turns, which is why phase guidance is delivered in the conversation rather than by recomposing the system prompt. Leon set caching as a required capability rather than an optimization. The byte-stable-prefix invariant this depends on is recorded as a separate constraint.
