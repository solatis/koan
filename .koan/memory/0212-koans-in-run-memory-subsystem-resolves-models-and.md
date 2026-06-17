---
title: koan's in-run memory subsystem resolves models and credentials from an explicit
  per-run MemoryModels bundle and a self-contained ModelSpec, deleting three module
  globals
type: decision
created: '2026-06-12T23:04:39Z'
modified: '2026-06-12T23:04:39Z'
related:
- 0196-koan-freezes-a-runs-resolved.md
- 0178-koan-provider-api-keys-stored-in-an-encrypted.md
- 0155-provider-config-reshaped-to-modelspec.md
---

koan's memory subsystem (`koan/memory/llm.py`, `koan/memory/retrieval/{backend,index,reflect,rag}.py`, `koan/memory/bindings.py`, and the in-process memory tools in `koan/tools/koan_tools.py`) resolved its chat, embedding, and rerank models and their API keys through process-wide module globals: `_ACTIVE` in `koan/credentials.py` (`set_active_credential_store` / `active_credential_store`) plus `_ACTIVE_CONFIG` and `_ACTIVE_FROZEN_MODELS` in `koan/memory/bindings.py`. Leon directed removing all three on 2026-06-12.

Motivating defect: during a run, in-run memory built its `ModelSpec` from the per-run frozen snapshot but still resolved `api_key` from the boot-time `active_credential_store` -- model and credential came from different sources, while the agent spawn path already resolved both from the per-run frozen snapshot. The task framed this as a 'stale boot-time global cannot find a UI-added credential' bug; investigation showed the live `_ACTIVE` store is the same mutable object the connection-edit endpoint writes to, so the real defect is the source asymmetry, not staleness.

New shape: `ModelSpec` (`koan/types.py`) gained a resolved `api_key` baked once at flatten time (`build_resolved_model` in `koan/agents/registry.py`; `build_memory_models` in `koan/memory/bindings.py`) from the relevant `CredentialStore`; it is in-memory only and is never written to `run-config.yaml`, subagent `task.json`, the projection wire, or logs. A frozen `MemoryModels` bundle (three Optional specs: `embedding`, `memory_llm`, `reflect_llm`) produced by the pure `build_memory_models(config, credential_store)` is threaded explicitly into every memory entry point and in-process memory tool. It is constructed at three sites: in-run at `api_start_run` and stored on `RunState.memory_models`; on demand from `app_state.provider_config` for the out-of-run web memory endpoints; and at process entry for the standalone `koan memory` CLI. The agent spawn path was unified to read `spec.api_key` too, dropping its spawn-time credential-store lookup in `koan/agents/pydantic_ai.py`. All three globals and their accessors were deleted.

Alternatives rejected: bypassing the globals only for the in-run path while leaving them for the CLI (leaves the very module globals the project's no-globals rule condemns); passing one `ModelSpec` per function instead of a bundle (the reflect loop and the mechanical RAG injection each need two bindings at once -- `reflect_llm` + `embedding`, `memory_llm` + `embedding` -- forcing multi-argument threading); and baking `api_key` only onto the memory specs while leaving the agent spawn path resolving at spawn time (two divergent credential-resolution sites).
