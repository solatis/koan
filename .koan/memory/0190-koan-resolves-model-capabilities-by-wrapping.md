---
title: koan resolves model capabilities by wrapping PydanticAI's ModelProfile and
  extending it with koan-sourced context-window and prompt-caching, keyed by (provider,
  model)
type: decision
created: '2026-06-08T23:35:36Z'
modified: '2026-07-13T08:29:54Z'
related:
- 0171-model-thinking-is-a-portable-koan-thinkingmode.md
- 0159-prompt-caching-is-required-configured-per.md
- 0172-usage-cost-and-context-window-percent-are-derived.md
---

koan resolves each configured model's capability set as a read-only `Capabilities`, never asking the user for a capability. Thinking shape (Anthropic adaptive-thinking-plus-effort vs discrete thinking budgets), web-search availability, and tool/json support come from PydanticAI's per-(provider, model) `ModelProfile` (via `infer_model_profile` and the per-provider `*_model_profile` functions). Context-window size, its variants, and prompt-caching support are koan-sourced because PydanticAI's profile exposes no context-window field. Capability is keyed by (provider, model), not by model alone, because the same family through different connections differs in capabilities and credentials. Leon directed building on PydanticAI as the engine and wrapping/extending only where koan needs its own facts, not reimplementing provider auth, model profiles, or capability tables PydanticAI already provides. The resolved set is surfaced read-only so the config surface never offers a control for a capability a (provider, model) lacks; e.g. a role-slot's chosen thinking mode is validated against the resolved `thinking_levels` and rejected if unsupported (deterministic, not a silent downgrade). The implementation lives in the `koan/models/` package: `koan/models/capabilities.py` holds the curated `_BASE_CATALOG` (model identity → base capabilities) and `_ROUTE_OVERLAYS` (per-route capability overrides for prompt_caching, native_tools, batches, etc.); `koan/models/offering.py` provides `resolve_offering` which merges the base catalog entry, route overlay, and PydanticAI profile into a final `Offering` with `Capabilities`; `koan/models/identity.py` parses model IDs into `(vendor, family, version, snapshot, kind)`; `koan/models/codecs.py` translates between wire IDs and `ModelIdentity` per route. The earlier implementation in `koan/agents/capability_resolver.py` and `koan/agents/model_catalog.py` is deleted; the `koan/models/` package replaced both. Alternatives rejected: resolving everything from PydanticAI (no context-window field); keeping koan's prior static `MODEL_CAPABILITIES` table as the primary authority (duplicates what profiles already encode).
