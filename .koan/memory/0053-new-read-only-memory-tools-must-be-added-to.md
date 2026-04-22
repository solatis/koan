---
title: New read-only MCP tools must be added to a tool-family-specific _UNIVERSAL_*_TOOLS
  frozenset in koan/lib/permissions.py
type: procedure
created: '2026-04-18T14:36:10Z'
modified: '2026-04-21T13:20:07Z'
related:
- 0066-synthesis-expensive-memory-tools-scoped-to.md
---

This entry documents the permission-fence pattern for making cheap cross-role MCP reads available without per-role enumeration. On 2026-04-21, Leon confirmed that new read-only MCP tools must be added to a tool-family-specific `_UNIVERSAL_*_TOOLS` frozenset in `koan/lib/permissions.py`; the fast-path branch for each frozenset appears in `check_permission()` before the orchestrator dispatch and before the role-specific `ROLE_PERMISSIONS` check, so every role (orchestrator, scout, planner, executor) inherits access through a single allow-statement. Two such frozensets exist: `_UNIVERSAL_MEMORY_TOOLS` (contains `koan_memory_status`, `koan_search`) and `_UNIVERSAL_READ_TOOLS` (contains `koan_artifact_list`, `koan_artifact_view`). The alternative of duplicating a tool name across every role's entry in `ROLE_PERMISSIONS` was rejected by Leon because per-role enumeration diverges over time as new roles are added. Expensive or synthesis-heavy tools (for example `koan_reflect`, per entry 66) remain orchestrator-only; universality is reserved for single-query reads. Adding a new read-only tool requires exactly two edits: add the tool name to the appropriate `_UNIVERSAL_*_TOOLS` frozenset, and register the MCP handler in `koan/web/mcp_endpoint.py`.
