---
title: Reshaping a core config type left stale runner_type reads in the web/settings
  layer that crashed app boot
type: lesson
created: '2026-06-04T14:20:27Z'
modified: '2026-06-04T14:20:27Z'
related:
- 0155-provider-config-reshaped-to-modelspec.md
- 0115-plan-spec-analysis-must-inventory-non-source.md
---

After the provider-config reshape replaced `ProfileTier`'s `runner_type` with a `ModelSpec`, a stale read of the removed field survived in the web layer -- `_serialize_profile` in `koan/web/app.py` still read `pt.runner_type` during startup config serialization -- and threw `AttributeError`, so the server never came up and koan was unusable. The reshape's plan had not enumerated every reader of the field; the long tail lived in the settings, profile, and probe endpoints, away from the core config module. Root cause: removing a core config field changes the contract for readers in peripheral layers (web/settings/probe) that a core-focused plan does not inventory. Prevention: when removing or renaming a core config field, grep every reader across the non-core layers -- especially the web/settings/probe endpoints -- and migrate them in the same change, because a single missed read can crash boot rather than fail locally.
