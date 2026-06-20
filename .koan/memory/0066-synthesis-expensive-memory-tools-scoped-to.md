---
title: Synthesis-expensive memory tools scoped to orchestrator-only; universal scope
  reserved for cheap single-query reads
type: decision
created: '2026-04-20T08:44:17Z'
modified: '2026-06-20T03:38:39Z'
related:
- 0053-new-read-only-memory-tools-must-be-added-to.md
---

koan scopes the `koan_reflect` memory tool to roles that should run multi-turn synthesis, not to every role. Although `koan_reflect` is read-only, Leon placed it in the orchestrator's role tool set (and later the reviewer's) rather than in the universal memory set, because a single `koan_reflect` call runs up to `MAX_ITERATIONS` (10) LLM turns (`koan/memory/retrieval/reflect.py`) with the model driving search and synthesis -- far more expensive and intent-heavy than a single-query read. Scouts and executors have focused, bounded tasks; `koan_search` (the cheap single-query path that IS universal) serves their needs at fixed cost. This is enforced by construction in `koan/tools/tool_policy.py`: `_UNIVERSAL_MEMORY_TOOLS` holds only the cheap reads (`koan_memory_status`, `koan_search`), while synthesis-expensive and write tools live in role-specific `ROLE_PERMISSIONS` sets, and `compose_toolset` registers only the composed set per (role, phase). Alternative rejected: making every read-only memory tool universal -- that would hand scouts and executors multi-turn LLM reasoning they do not need and whose cost they cannot budget.
