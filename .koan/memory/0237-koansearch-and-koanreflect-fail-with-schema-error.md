---
title: 'koan_search and koan_reflect fail with ''Schema Error: Provided schema does
  not match existing table schema'' when the retrieval index schema drifts from the
  code'
type: lesson
created: '2026-06-22T02:15:46Z'
modified: '2026-06-22T02:15:46Z'
---

koan's memory retrieval -- koan_search (hybrid dense + BM25 with rerank) and koan_reflect, backed by the vector index under .koan/memory/ using Voyage AI embeddings -- returned 'Schema Error: Provided schema does not match existing table schema' (and 'invalid_type') on every call throughout a full workflow run, so semantic search and synthesis were unavailable to the intake, plan-review, and curation phases. Root cause: the persisted index table's schema had drifted from the schema the current retrieval code expects; the queries themselves were well-formed, so this was a stored-index/code version mismatch rather than a query bug. The fallback that kept curation working: koan_memory_status still returned the project summary and the full entry listing (id, title, type, dates), and entry bodies were read directly from .koan/memory/NNNN-*.md -- together enough for duplicate-detection and classification without semantic ranking.
