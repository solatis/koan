---
title: Three-tier model system (strong/standard/cheap) over per-role model configuration
type: decision
created: '2026-04-16T07:35:45Z'
modified: '2026-04-16T07:35:45Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
---

The model selection system in koan (`koan/config.py`, `docs/subagents.md` -- Model Tiers section) was designed on 2026-02-10 when Leon grouped the 6+ agent roles into three capability tiers rather than mapping each role to an individual model. Leon defined the tiers as: `strong` (orchestrator -- complex multi-step reasoning), `standard` (executor -- reliable tool use for code implementation), and `cheap` (scout -- narrow codebase investigation). Leon encoded the role-to-tier mapping in `koan/config.py`. Leon adopted a profile-based configuration system persisted to `~/.koan/config.json` that binds each tier to a specific runner type and model name; switching profiles changes all three tier bindings at once without touching role definitions. Leon rejected per-role model configuration because, with 6+ roles, each model change would require updating 6+ bindings; the tier system reduces that to 3 bindings per profile switch.
