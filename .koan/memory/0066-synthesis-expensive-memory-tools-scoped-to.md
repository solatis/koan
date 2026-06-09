---
title: Synthesis-expensive memory tools scoped to orchestrator-only; universal scope
  reserved for cheap single-query reads
type: decision
created: '2026-04-20T08:44:17Z'
modified: '2026-04-20T08:44:17Z'
related:
- 0053-new-read-only-memory-tools-must-be-added.md
---

This entry documents a permission-scope choice in koan's permission fence `koan/lib/permissions.py` for the `koan_reflect` memory tool implemented on 2026-04-20. Leon decided that `koan_reflect` is a read-only memory tool but was added to `_ORCHESTRATOR_MEMORY_TOOLS` rather than to `_UNIVERSAL_MEMORY_TOOLS`. Rationale: a single `koan_reflect` call runs up to 10 Gemini 2.5 Pro turns (the `MAX_ITERATIONS` constant in `koan/memory/retrieval/reflect.py`) with the LLM driving search and synthesis, making it considerably more expensive and intent-heavy than a single-query read. Scouts and executors have focused, bounded tasks; `koan_search` (the cheap single-query retrieval path already in `_UNIVERSAL_MEMORY_TOOLS`) serves their needs at fixed cost. The decision refines the rule recorded in `0053-new-read-only-memory-tools-must-be-added-to.md`: `_UNIVERSAL_MEMORY_TOOLS` is for cheap single-query reads (`koan_memory_status`, `koan_search`); synthesis-expensive read tools and write tools go in role-specific permission sets. Alternative rejected: extending the blanket rule ("New read-only memory tools must be added to `_UNIVERSAL_MEMORY_TOOLS`") to cover reflect -- would have given scouts and executors access to multi-turn LLM reasoning they do not need and whose cost they cannot budget.
