---
title: Three-tier model system (strong/standard/cheap) over per-role model configuration
type: decision
created: '2026-04-16T07:35:45Z'
modified: '2026-06-04T14:26:45Z'
related:
- 0155-provider-config-reshaped-to-modelspec.md
---

koan groups its agent roles into three model capability tiers rather than mapping each role to an individual model. Leon defined the tiers as `strong` (orchestrator -- complex multi-step reasoning), `standard` (executor -- reliable tool use for implementation), and `cheap` (scout -- narrow codebase investigation), with the role-to-tier mapping encoded in `koan/config.py`. A profile persisted to `~/.koan/config.json` binds each tier to a `ModelSpec` (its provider, model, thinking, and caching settings); switching profiles re-points all three tiers at once without touching role definitions. Leon rejected per-role model configuration because, with six or more roles, every model change would mean updating six or more bindings; the tier system reduces that to three bindings per profile. The tier binds to a `ModelSpec` (a provider and model), not to a CLI runner type -- provider availability comes from resolved environment credentials, not from a detected CLI binary.
