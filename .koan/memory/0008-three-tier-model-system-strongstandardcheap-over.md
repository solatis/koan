---
title: Three-tier model system (strong/standard/cheap) over per-role model configuration
type: decision
created: '2026-04-16T07:35:45Z'
modified: '2026-06-20T00:15:23Z'
related:
- 0155-provider-config-reshaped-to-modelspec.md
- 0189-koan-providermodel-config-layered-as-flat.md
---

koan groups its agent roles into three model capability tiers rather than mapping each role to an individual model. Leon defined the tiers as `strong` (orchestrator -- complex multi-step reasoning), `standard` (executor -- reliable tool use for implementation), and `cheap` (scout -- narrow codebase investigation), with the role-to-tier mapping encoded in `koan/config.py`. Each tier is a role-slot that references one configured model (a connection plus model-id); the three slots are persisted in `~/.koan/config.yaml` and re-point all three roles at once without touching role definitions. Leon rejected per-role model configuration because, with six or more roles, every model change would mean updating six or more bindings; the tier system reduces that to three. The earlier named `Profile` bundle that held the strong/standard/cheap triple was later replaced by a `presets`-plus-`active` mechanism (today a single reserved `$last` preset), but the three-tier grouping survived that config cutover unchanged. A tier binds to a provider-and-model pair, not to a CLI runner type -- provider availability comes from resolved provider credentials (an encrypted CredentialStore), not from a detected CLI binary.
