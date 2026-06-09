---
title: 'Cache-prefix stability is load-bearing: a byte change to the agent loop''s
  system prompt + tool defs + early history invalidates the cache'
type: context
created: '2026-06-04T14:16:33Z'
modified: '2026-06-04T14:16:33Z'
related:
- 0159-prompt-caching-is-required-configured-per.md
- 0157-tool-vocabulary-is-restricted-at-toolset.md
- 0160-context-files-agentsmdclaudemd-are-injected-just.md
---

koan's prompt caching keys on the agent loop's cacheable prefix -- the system prompt, the tool definitions, and the early conversation history -- so any byte change to that prefix between turns invalidates the cache and forces a full re-encode. Keeping the prefix byte-stable within a phase is therefore load-bearing, and it explains the shape of several agent-layer designs: phase guidance is delivered as conversation messages instead of recomposing the system prompt at each phase; tool vocabulary is composed per (role, phase) rather than per step (`compose_toolset`), so the tool-definition block does not change between steps; context files arrive as separate user messages instead of being merged into the system prompt; and steering and context injections land at request boundaries instead of mutating earlier messages. One tension is left deliberately unresolved rather than treated as a bug: whether to recompose the system prompt at phase boundaries (accepting a single cache miss for a cleaner prompt) or never recompose it. This matters because an agent editing the loop, the toolset composition, or the injection points can silently destroy caching by perturbing the prefix.
