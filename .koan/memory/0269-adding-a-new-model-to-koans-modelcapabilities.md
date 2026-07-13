---
title: "Adding a new model to koan's _BASE_CATALOG requires coordinated updates to\
  \ identity families, cache overlays, and genai-prices \u2014 all applied together\
  \ before tests pass"
type: procedure
created: '2026-07-02T06:05:50Z'
modified: '2026-07-13T08:29:54Z'
related:
- 0190-koan-resolves-model-capabilities-by-wrapping.md
- 0238-prompt-caching-capability-is-keyed-on-connection.md
---

koan's model catalog (`_BASE_CATALOG` in `koan/models/capabilities.py`) and identity layer (`koan/models/identity.py`) maintain cross-referencing data structures that must stay in sync. When adding a new model to `_BASE_CATALOG`, apply all of the following together before running tests:

1. Add the catalog entry to `_BASE_CATALOG` in `koan/models/capabilities.py` with the model's `ModelIdentity` (vendor, family, version, snapshot, kind) and base `Capabilities` (thinking_levels, prompt_caching, native_tools, etc.).
2. If the model introduces a new family (e.g., `claude-fable`): ensure `koan/models/identity.py` can parse the model ID into the correct family. The identity parser uses regex patterns per vendor; a new family may need a new pattern or an extension to an existing one. Without this, `parse_model_id` returns an unrecognized identity and `resolve_offering` cannot match the catalog entry.
3. If the model supports prompt caching on an explicit-cache route (anthropic or bedrock): ensure the route's `_ROUTE_OVERLAYS` entry in `koan/models/capabilities.py` has `prompt_caching="explicit"` and that the model's family is covered by the overlay. Without this, `resolve_offering` produces caps with `prompt_caching="none"` and the cache guard skips the route.
4. Bump the `genai-prices` dependency floor in `pyproject.toml` if the model is not in the current bundled price snapshot, then run `uv lock` from the project root. Every catalog entry must resolve a positive price in the snapshot — the parametrized test `test_offered_model_price_resolves` enforces this.

The parametrized test `test_anthropic_returns_true` iterates all anthropic models in `_BASE_CATALOG` and asserts `supports_prompt_caching` returns `True`. This test passes only when all infrastructure changes (identity parsing + catalog entry + overlay) are in place. Adding the catalog entry alone, without the identity and overlay entries, causes this test to fail — the model is cataloged but `resolve_offering` cannot resolve its route-aware caps.

Adapter (`map_thinking` in `koan/agents/adapter.py`) and capability changes are needed only when pydantic-ai lacks a profile for the model or the existing thinking-shape path does not cover the model's thinking mode. When pydantic-ai already has a profile (verified via the per-provider `*_model_profile` functions), the `koan/models/` package entries above are the only koan-side changes required.
