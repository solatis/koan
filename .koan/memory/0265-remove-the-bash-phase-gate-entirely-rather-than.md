---
title: Remove the bash phase gate entirely rather than expanding the allowlist
type: decision
created: '2026-07-01T06:19:12Z'
modified: '2026-07-01T06:19:12Z'
---

The orchestrator's bash tool — the user decided to remove the `_ORCHESTRATOR_BASH_PHASES` phase gate entirely from `koan/tools/tool_policy.py`, making bash a default-always tool for the orchestrator like `read`, `grep`, and `glob`. Rationale: the governing principle is "anywhere read access is allowed, bash is allowed," and a phase gate on bash has no enforcement value — the permission layer cannot distinguish read-bash from write-bash, so prompt engineering is the only constraint. Alternatives rejected: expanding `_ORCHESTRATOR_BASH_PHASES` to include all phases — this would be a no-op gate requiring maintenance when phases are added or removed, with zero enforcement value. The decision surfaced when the user noted bash was unavailable during the intake phase, where it is a convenient exploration tool.
