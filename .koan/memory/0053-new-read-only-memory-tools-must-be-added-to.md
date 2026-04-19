---
title: New read-only memory tools must be added to _UNIVERSAL_MEMORY_TOOLS in koan/lib/permissions.py
type: procedure
created: '2026-04-18T14:36:10Z'
modified: '2026-04-18T14:36:10Z'
---

The permission gate in `koan/lib/permissions.py` provides a universal fast-path for read-only memory query tools via the `_UNIVERSAL_MEMORY_TOOLS` frozenset. On 2026-04-18, Leon identified that `koan_memory_status` and `koan_search` had been accidentally scoped to the orchestrator role only -- they appeared in `_ORCHESTRATOR_MEMORY_TOOLS` but were absent from the non-orchestrator `ROLE_PERMISSIONS` dicts (`scout`, `executor`, `intake`, `planner`), causing scouts and executors to be silently blocked from querying memory. Leon directed the fix: add both tools to a new `_UNIVERSAL_MEMORY_TOOLS` frozenset placed between the `_NON_BASH_READ_TOOLS` fast-path and the orchestrator branch in `check_permission()`. The resulting behavioral rule: any new read-only memory tool added to the koan MCP endpoint must also be registered in `_UNIVERSAL_MEMORY_TOOLS` to be available for all agent roles. Placing a new memory read tool only in `_ORCHESTRATOR_MEMORY_TOOLS` will silently restrict it to the orchestrator with no error.
