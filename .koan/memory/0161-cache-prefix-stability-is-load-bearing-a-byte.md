---
title: 'Cache-prefix stability is load-bearing: a byte change to the agent loop''s
  system prompt + tool defs + early history invalidates the cache'
type: context
created: '2026-06-04T14:16:33Z'
modified: '2026-06-30T08:09:17Z'
related:
- 0238-prompt-caching-capability-is-keyed-on-connection.md
- 0239-koan-fails-fast-at-runtime-when-a-caching-capable.md
- 0159-prompt-caching-is-required-configured-per.md
- 0157-tool-vocabulary-is-restricted-at-toolset.md
- 0160-context-files-agentsmdclaudemd-are-injected-just.md
---

koan's prompt caching keys on the agent loop's cacheable prefix -- the system prompt, the tool definitions, and the early conversation history -- so any byte change to that prefix between turns invalidates the cache and forces a full re-encode. Keeping the prefix byte-stable within a phase is therefore load-bearing, and it explains the shape of several agent-layer designs: phase guidance is delivered as conversation messages instead of recomposing the system prompt at each phase; tool vocabulary is composed per (role, phase) rather than per step (`compose_toolset`), so the tool-definition block does not change between steps; context files arrive as separate user messages instead of being merged into the system prompt; and steering and context injections land at request boundaries instead of mutating earlier messages. A tension that had been left deliberately unresolved -- whether to recompose context at phase boundaries (accepting a single cache miss for a cleaner prompt) or never recompose it -- was resolved on 2026-06-30 toward resetting: `reset_phase_context` now clears the orchestrator's `message_history` at every phase boundary and the pre-seed rebuilds a minimal per-phase context, so cache-prefix stability is load-bearing WITHIN a phase while one re-encode miss is accepted at each phase entry. This matters because an agent editing the loop, the toolset composition, or the injection points can silently destroy caching by perturbing the prefix. A runtime guard now backstops this risk: koan/agents/cache_guard.py (check_cache_effectiveness), called from run_agent_loop at each turn boundary, fails fast with AgentError(code="prompt_cache_ineffective") when a caching-capable route re-sends substantial input across multiple requests yet produces zero cache reads, so a prefix perturbation severe enough to zero out caching surfaces as a hard error instead of silent budget burn.
