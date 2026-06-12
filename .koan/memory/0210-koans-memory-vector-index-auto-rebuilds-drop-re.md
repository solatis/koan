---
title: koan's memory vector index auto-rebuilds (drop + re-embed all) when the embedding
  binding's model or dimension changes, triggered at config-save
type: decision
created: '2026-06-12T05:07:27Z'
modified: '2026-06-12T05:07:27Z'
related:
- 0031-voyage-ai-as-sole-retrieval-provider-voyage-4.md
- 0034-koan-memory-sync-uses-sha-256-content-hash-not.md
- 0196-koan-freezes-a-runs-resolved.md
---

koan memory retrieval index (`koan/memory/retrieval/index.py`, `koan/web/app.py`). Leon directed that the LanceDB memory index automatically rebuild whenever the active embedding binding's effective identity changes, where identity is the (model_id, resolved output dimension) pair. The rebuild drops the LanceDB table and re-embeds every memory entry at the new model and dimension via `RetrievalIndex.rebuild()`. It fires at config-save: `api_config_model_set` and `api_config_memory_set` compute the embedding binding's effective identity (`_effective_embedding_identity`, a pure non-raising helper) before mutating the config and again after saving, and rebuild only when the two differ. A user-facing warning is shown before the change is committed, but the rebuild then runs automatically and synchronously.

This supersedes the project's earlier stance -- previously recorded only in code comments -- that changing the embedding model or dimension required a MANUAL vector-store rebuild with no auto re-index. Leon's rationale: because the dimension is configurable, users would change it after the index exists, and a silent model/dimension mismatch (which mixes incompatible embedding vector spaces or breaks the fixed-width LanceDB vector schema) is unacceptable; co-locating the rebuild with the user's confirmed action keeps cause and effect together.

The trigger covers model OR dimension change, not dimension alone: switching the embedding model at the same dimension changes the embedding vector space without changing the LanceDB schema width, so a dimension-only trigger would silently mix embeddings from two models. Alternatives rejected: detecting the change from the LanceDB schema alone (the schema records the dimension but not the model, so a same-dimension model swap is invisible); a lazy rebuild deferred to the next index sync (rejected so the re-embed cost lands on the user's deliberate action, not the next search); persisting the index's embedding identity in a sidecar file or table metadata (the save-time before/after config comparison covers every config-UI path without it). The save-time trigger depends on the memory subsystem reading the live active provider config -- the same KoanConfig object the config endpoints mutate in place -- distinct from the frozen per-run config snapshot the workflow agents read.
