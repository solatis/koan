---
title: Voyage embedding models are a koan-owned static catalog (voyage-4-large / voyage-4
  / voyage-4-lite) with a user-selectable, persisted output dimension whitelisted
  in UI and backend
type: decision
created: '2026-06-12T05:07:19Z'
modified: '2026-06-12T05:07:19Z'
related:
- 0031-voyage-ai-as-sole-retrieval-provider-voyage-4.md
- 0127-static-shared-state-surfaces-via-projection.md
---

koan memory embedding configuration (`koan/memory/bindings.py`, `koan/web/app.py`, the Settings -> Memory UI). Leon directed adding a koan-owned static catalog of the recognized Voyage embedding models -- `voyage-4-large`, `voyage-4`, `voyage-4-lite` -- each with a fixed (non-user-editable) 32,000-token context window and a set of selectable output dimensions (256, 512, 1024, 2048; default 1024). The catalog is `VOYAGE_EMBEDDING_MODELS` in `koan/memory/bindings.py`, replacing the prior single-entry `EMBEDDING_DIMS` mapping. The user's chosen dimension persists as a new optional `ConfiguredModel.embedding_dim` (None = the model's default), threaded through `resolve_memory_binding` into the Voyage `embed(output_dimension=...)` call and the LanceDB vector schema; the context window is fixed and only the dimension is user-selectable.

Rationale and rejected alternatives: the catalog is deliberately NOT added to `MODEL_CAPABILITIES` / `build_model_registry` in `koan/agents/model_catalog.py`, because a validating test requires every entry there to resolve to a positive completion price in the bundled genai-prices snapshot, which Voyage embedding models have no entry for -- so the koan-owned `bindings.py` table is the embedding-specific home. The catalog is surfaced to the frontend through a dedicated `embedding_models_listed` projection event into a new `Settings.embedding_models` field, NOT by injecting Voyage rows into the snapshot-bound chat `model_registry` (whose `ModelRegistryEntry` carries no dimensions field), keeping the chat registry free of embedding concerns and following the read-via-projection convention. Embedding-model selection is whitelisted to the three recognized models, enforced both in the frontend ModelPicker (free-text entry disabled for Voyage) and at the config-write endpoints (`api_config_model_set` / `api_config_memory_set` return HTTP 422 for an unrecognized Voyage model id or an out-of-set dimension); Leon chose enforcement in both layers (defense in depth) over UI-only or backend-only.
