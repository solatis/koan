---
title: Usage cost and context-window percent are derived in the projection fold from
  the genai-prices bundled snapshot, for fold determinism
type: decision
created: '2026-06-05T13:06:28Z'
modified: '2026-06-05T13:06:28Z'
related:
- 0019-projection-events-record-facts-derived-state.md
- 0155-provider-config-reshaped-to-modelspec.md
- 0162-the-agent-layer-emits-a-fixed-8-type-streamevent.md
---

koan's header usage gauges show cost, context-window percent, and cache read/write tokens beside the token counts. On 2026-06-05, Leon's usage-gauge work fixed how these are computed: the per-agent projection `Conversation` (`koan/projections.py`) carries `cache_read_tokens` and `cache_write_tokens` as folded FACTS, and `total_cost_usd` and `context_window_percent` as values DERIVED inside the projection fold, so the browser renders them with no computation. The agent's provider, model, and context window ride the agent-spawned event (and `AgentState`), so the fold derives without any live config lookup, keeping the fold pure. Cost is computed by `koan/agents/model_catalog.py:price_for_usage`, which calls genai-prices `calc_price` against its BUNDLED SNAPSHOT only; the network-refresh path (`UpdatePrices`) is never enabled, because the fold must be deterministic -- the same event stream must always fold to the same projection, and a live price refresh would break that. A validating unit test (`tests/test_model_catalog.py`) asserts every offered and built-in-profile model price-resolves against the bundled snapshot, so an unpriced model fails the build rather than silently showing no cost. The fold is guarded: `price_for_usage` runs in try/except (keeping the prior cost on failure) and the context-window division runs only when context_window is greater than zero. `context_window_percent` is the most recent request's input tokens divided by the context window, clamped to 0-100 (current context fullness, not a cumulative sum across turns).
