---
title: "Bash was phase-gated for the orchestrator but should follow the read-tools\
  \ principle \u2014 anywhere read access is allowed, bash is allowed"
type: lesson
created: '2026-07-01T06:19:12Z'
modified: '2026-07-01T06:19:12Z'
---

The orchestrator's `bash` tool in `koan/tools/builtin_tools.py` was restricted to only the `execute` and `frame` phases via `_ORCHESTRATOR_BASH_PHASES` in `koan/tools/tool_policy.py`, enforced at call time by `phase_gate_message`. The user corrected this: bash should not be gated during intake or any phase — it is a convenient exploration tool, and the governing principle is "anywhere read access is allowed, bash is allowed." Non-orchestrator roles (scout, executor, reviewer) already had bash unconditionally via `compose_toolset`, making the orchestrator restriction an inconsistency. The architecture doc already stated "bash is in READ_TOOLS and always allowed" — the code just didn't match. Root cause: bash was classified alongside `koan_request_executor` and `koan_request_scouts` as a "phase-conditional" tool, but bash is fundamentally a read/exploration tool in the same category as `read`, `grep`, and `glob`. Prevention: bash should be a default-always tool for all roles, never added to a phase gate.
