---
title: "Model\u2192tier mapping (tier_hint) removed from koan \u2014 tier system is\
  \ unidirectional (tier\u2192model only)"
type: decision
created: '2026-07-10T17:26:09Z'
modified: '2026-07-10T17:26:09Z'
related:
- 0008-three-tier-model-system-strongstandardcheap-over.md
- 0269-adding-a-new-model-to-koans-modelcapabilities.md
---

koan's model tier system — Leon decided to remove the model→tier mapping (`tier_hint`) from koan entirely, making the tier system unidirectional: tier→model only (a tier slot references a configured model), never model→tier (a model does not have an intrinsic tier). Rationale: a model's tier depends on run-specific slot assignment, not on the model's identity. The idea that a model should *always* be tier X is wrong — the same model could be assigned to different tiers in different runs. The tier→model direction (role-slots in `ROLE_MODEL_TIER` in `koan/types.py`, the `ModelTier` type, the `ALL_MODEL_TIERS` constant, and the presets/`$last` slot config) stays because "by default, for tier X use model Y" is a valid user-controlled assignment. The `tier_hint` field existed in two independent sources: `_FAMILY_TABLE` in `koan/agents/recognition.py` (family key → tier_hint + display_group) and `MODEL_CAPABILITIES` in `koan/agents/model_catalog.py` ((provider, model) → thinking_modes + tier_hint + fallback_display_name). It was plumbed through `ParsedModel`, `ResolvedCapabilities`, `ModelRegistryEntry`, SSE projection wire types (`ResolvedCapabilitiesWire`, `ModelRegistryEntryWire`), API serialization (`koan/web/app.py`), and frontend store types (`frontend/src/store/index.ts`), but consumed by nothing — no logic read it, no component rendered it. The dead `_TIER_DEFAULT_THINKING` dict in `koan/agents/registry.py` (zero call sites) was also removed. Alternatives rejected: keeping `tier_hint` as null-optional wire fields for backward compatibility (no consumer reads it; SSE replace-all semantics make this unnecessary); keeping `_TIER_DEFAULT_THINKING` as tier-slot-related rather than model→tier dead code (it is dead regardless of categorization). Decision surfaced when Leon reviewed a findings report documenting that tier_hint was plumbed everywhere and used nowhere.
