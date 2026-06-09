---
title: koan's selectable model list is fetched live per connection (no bundled baseline);
  'newest in family' resolves at config time to a pinned version with recorded provenance
type: decision
created: '2026-06-08T23:35:41Z'
modified: '2026-06-08T23:35:41Z'
related:
- 0184-local-ai-lm-studio-support-keyless-openai.md
---

For choosing which model to configure on a connection, koan retrieves the selectable list live from the provider on demand (`list_models_for_connection` in `koan/agents/model_listing.py`, for the listing-capable connection types OpenAI/Anthropic/Google/LM Studio) and otherwise accepts free-text entry; there is no bundled, periodically-updated baseline the user selects from. Leon resolved this open question for live-on-query plus free-text after weighing the alternatives: a one-time static list (stale immediately, and koan cannot enumerate a local LM Studio install), a bundled/library registry (maintenance burden, still stale), and a boot-time probe of every provider (network at startup, which koan keeps network-free). The genai-prices snapshot and `koan/agents/model_catalog.py` remain, but only for pricing and context-window facts, not as the selectable source. Separately, 'newest model in a family' is a config-time convenience only: `resolve_newest_in_family` (`koan/agents/newest_in_family.py`) resolves the family against the live list using the recognition layer's version ordering, writes the resulting PINNED model-id into the config, and records what it resolved to as provenance. koan never stores a floating request-time 'latest' pointer -- the default everywhere is a pinned version -- because a floating alias makes the resolved model non-deterministic across runs.
