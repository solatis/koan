---
title: "Adding a new model to koan's MODEL_CAPABILITIES requires coordinated updates\
  \ to recognition families, cache families, and genai-prices \u2014 all applied together\
  \ before tests pass"
type: procedure
created: '2026-07-02T06:05:50Z'
modified: '2026-07-02T06:05:50Z'
related:
- 0190-koan-resolves-model-capabilities-by-wrapping-pydanticai-modelprofile-and-extending-it-with-koan-sourced-context-window-and-prompt-caching-keyed-by-provider-model.md
- 0238-prompt-caching-capability-is-keyed-on-connection-transport-model-family-and-one-cachingpolicy-is-translated-to-per-transport-keys-anthropic-cache-vs-bedrock-cache.md
---

koan's model catalog (`koan/agents/model_catalog.py`) and recognition layer (`koan/agents/recognition.py`) maintain cross-referencing data structures that must stay in sync. When adding a new model to `MODEL_CAPABILITIES`, apply all of the following together before running tests:

1. Add the `(provider, model)` entry to `MODEL_CAPABILITIES` in `koan/agents/model_catalog.py` with `(thinking_modes, tier, display_name)`.
2. If the model introduces a new family (e.g., `claude-fable`): add the family to `_FAMILY_TABLE` in `koan/agents/recognition.py` with `(tier_hint, display_group)`, and add the family name to the `_RE_CLAUDE_NEW` regex alternation (for Claude-family models). Without both, `parse_model_id` returns `recognized=False` for the new model id.
3. If the model supports prompt caching on an explicit-cache transport (anthropic or bedrock): add the family to `_EXPLICIT_CACHE_FAMILIES` in `koan/agents/model_catalog.py`. Without this, `supports_prompt_caching` returns `False` for the model.
4. Bump the `genai-prices` dependency floor in `pyproject.toml` if the model is not in the current bundled price snapshot, then run `uv lock` from the project root. Every `MODEL_CAPABILITIES` entry must resolve a positive price in the snapshot — the parametrized test `test_offered_model_price_resolves` enforces this.

The parametrized test `test_anthropic_returns_true` iterates all anthropic models in `MODEL_CAPABILITIES` and asserts `supports_prompt_caching` returns `True`. This test passes only when all three infrastructure changes (recognition regex + family table + cache family) are in place alongside the `MODEL_CAPABILITIES` entry. Adding the `MODEL_CAPABILITIES` entry alone, without the recognition and cache-family entries, causes this test to fail — the model is cataloged but `parse_model_id` cannot resolve its family, so `supports_prompt_caching` returns `False`.

Adapter (`map_thinking` in `koan/agents/adapter.py`) and capability-resolver changes are needed only when pydantic-ai lacks a profile for the model or the existing thinking-shape path does not cover the model's thinking mode. When pydantic-ai already has a profile (verified via the per-provider `*_model_profile` functions), the catalog-layer entries above are the only koan-side changes required.
