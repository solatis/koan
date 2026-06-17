---
title: koan_search/koan_reflect 'schema mismatch' traced to two koan installs sharing
  ~/.koan/ with different vector-DB backend versions; koan_memory_status + direct
  file reads are the fallback
type: lesson
created: '2026-06-14T10:06:13Z'
modified: '2026-06-14T10:49:22Z'
related:
- 0203-two-koan-installs-coexist-during-the-refactoring.md
- 0210-koans-memory-vector-index-auto-rebuilds-drop.md
---

Throughout a full initiative workflow, every koan_search and koan_reflect call returned "Schema Error: Provided schema does not match existing table schema", so semantic memory search and the synthesis tool were unusable for the whole run. koan_memory_status (which reads the .koan/memory/*.md entry files directly, not the vector index) and direct file reads kept working, so memory stayed usable via the file path. Root cause (per Leon): two koan installs share the same ~/.koan/ directory -- and therefore the same on-disk vector database under it -- but run different koan versions with different versions of the vector-database backend (the LanceDB-based memory index); the index schema one install's backend writes is incompatible with the other's reader, producing the schema-mismatch error. Two koan installs coexisting under ~/.koan/ is a known refactoring-era state (one on ~/.koan/config.json, one on ~/.koan/config.yaml). This is distinct from koan's intended index auto-rebuild, which triggers only on an embedding model/dimension change at config-save and would not reconcile a cross-version backend-schema divergence. Prevention: do not run multiple koan versions against a shared ~/.koan/ vector index -- isolate the memory index per install or align the vector-database backend version across installs; when the schema error nonetheless appears, fall back to koan_memory_status plus direct reads of .koan/memory/*.md for the run.
