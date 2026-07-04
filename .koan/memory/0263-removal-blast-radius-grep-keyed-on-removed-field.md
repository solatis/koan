---
title: Removal blast-radius grep keyed on removed field names misses consumers broken
  by the signature change
type: lesson
created: '2026-07-01T01:22:39Z'
modified: '2026-07-01T01:22:39Z'
related:
- 0256-grep-and-migrate-both-when-changing-production-signature.md
---

koan memory subsystem (`koan/memory/retrieval/rag.py`, `koan/memory/retrieval/reflect.py`, `koan/cli/memory.py`) -- when the dedicated `memory_llm`/`reflect_llm` fields were removed from `MemoryModels`, the plan inventoried the test blast radius by grepping `tests/` for the literal strings `memory_llm` and `reflect_llm` and treated the matching files as the complete set. That grep missed 6+ files under `tests/memory/` that were broken not by referencing the removed field names but by the call-signature change the removal entailed: `inject()` in `koan/memory/retrieval/rag.py` changed from taking a single `MemoryModels` object to taking separate `embed: ModelSpec` and `llm: ModelSpec` arguments; `_build_agent()` in `reflect.py` and `cmd_status()` in `koan/cli/memory.py` similarly changed from a `MemoryModels` argument to a `ModelSpec`/`None`. The broken call sites contain `real_memory_models`, `inject(`, and `MemoryModels()`, not the strings `memory_llm` or `reflect_llm`, so a name-keyed grep returns zero matches for them. The plan-phase review and the executor each independently surfaced a tranche of these files the grep had missed.

Root cause: a blast-radius grep keyed on the names of the removed fields finds only consumers that name those fields; it is blind to consumers broken by the signature change that reference the changed function or pass the whole object positionally. A field removal that also changes a function signature produces two disjoint sets of broken consumers, and only one set contains the removed names.

Prevention: when a refactor removes named fields AND changes a function signature, grep for both signals independently -- the removed field names AND the call sites of every function whose signature changed (e.g. `inject(`, `_build_agent(`, `cmd_status(`) -- across the entire test tree. Treat a zero-match grep on the removed names as necessary but not sufficient. This complements the existing rule to grep the entire test tree including skipif-gated and addopts-excluded modules.
