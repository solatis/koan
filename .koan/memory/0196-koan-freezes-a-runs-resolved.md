---
title: koan freezes a run's resolved provider/model/credential config at start-run
  (RunState snapshot + run-config.yaml) instead of resolving live per agent spawn
type: decision
created: '2026-06-10T09:52:21Z'
modified: '2026-06-12T23:05:07Z'
related:
- 0195-koans-frontend-profile-management-ui-was-deleted.md
- 0189-koan-providermodel-config-layered-as-flat.md
- 0155-provider-config-reshaped-to-modelspec.md
- 0212-koans-in-run-memory-subsystem-resolves-models-and.md
---

koan's run-launch path (`koan/web/app.py:api_start_run`, `koan/state.py:RunState`, `koan/config.py`, `koan/subagent.py`, `koan/agents/pydantic_ai.py`) denormalizes a run's model configuration at start time rather than resolving it live on every agent spawn. On 2026-06-10 Leon directed this while integrating the provider/model config UI. `api_start_run` deep-copies the live `KoanConfig` (which already bundles `connections`, the Fernet `credentials` envelopes, `configured_models`, and the `presets`/`active` pointer), applies any per-run model overrides, builds a frozen `CredentialStore` over the copy, stores both on `RunState.frozen_config` / `RunState.frozen_credential_store`, and serializes the frozen config to `<run_dir>/run-config.yaml`. The two spawn-time reads -- model resolution in `koan/subagent.py` and credential resolution in `koan/agents/pydantic_ai.py:run()` -- read the frozen snapshot instead of `app_state.provider_config.config` / `credential_store`. Per-run overrides are applied by writing an ephemeral `ConfiguredModel` with id `override:<slot>` (strong/standard/cheap) into the frozen `$last` preset only; `save_koan_config` is never called for them, so the persisted `~/.koan/config.yaml` slot assignments are untouched.

Rationale (Leon's framing): a run should denormalize its provider/model/auth config so it is immune to settings edits made while it runs, and so `run-config.yaml` is a durable, auditable on-disk record of exactly which connections/models/credentials a run used; the file carries the same opaque Fernet ciphertext envelopes as `config.yaml`, never plaintext.

Alternatives rejected: keeping the snapshot in-memory on `RunState` only (Leon directed mid-implementation that it must also be serialized to disk, since an in-memory-only copy is lost on restart and leaves no record); surfacing the denormalized config on the projection `RunConfig` SSE wire (redundant -- the per-agent model already renders at runtime and the durable record is `run-config.yaml`, so the wire was left unchanged); a per-role resolved-`ModelSpec` map (more invasive than passing the frozen config/store as inputs to the unchanged `resolve_model_spec` / `resolve_provider_auth`). The memory subsystem's separate `active_credential_store()` was deliberately left on the live config -- only the workflow agents read the frozen snapshot.

On 2026-06-12 Leon directed removing the final asymmetry above. The memory subsystem's `active_credential_store()` and the memory-binding globals `_ACTIVE_CONFIG` / `_ACTIVE_FROZEN_MODELS` were deleted, `ModelSpec` gained an `api_key` baked at flatten time, and in-run memory now resolves its models and credentials from the same per-run frozen state as the workflow agents -- threaded as an explicit `MemoryModels` bundle built at `api_start_run` and stored on `RunState.memory_models`, not read from a module global. Both the workflow-agent path and the in-run memory path now read the per-run frozen snapshot exclusively.
