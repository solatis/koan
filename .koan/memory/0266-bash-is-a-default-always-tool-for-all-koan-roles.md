---
title: Bash is a default-always tool for all koan roles; the principle is "anywhere
  read access is allowed, bash is allowed"
type: procedure
created: '2026-07-01T06:19:12Z'
modified: '2026-07-01T06:19:12Z'
---

When adding a new phase or role to koan, bash should be available by default — never add it to a phase gate or role restriction. The governing principle: anywhere read access is allowed, bash is allowed. Bash is an exploration tool in the same category as `read`, `grep`, and `glob`, not a privileged operation like `koan_request_executor` or `koan_request_scouts`. The wrong approach is adding bash to `_ORCHESTRATOR_BASH_PHASES` or any similar allowlist — this creates a no-op gate with zero enforcement value (the permission layer cannot distinguish read-bash from write-bash) and requires maintenance when phases are added or removed. Violating this leads to the orchestrator being unable to use bash for exploration in phases where read access is otherwise unrestricted, as happened when bash was gated to only `execute` and `frame` phases.
