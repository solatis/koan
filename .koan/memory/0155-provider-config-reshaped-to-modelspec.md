---
title: Provider config reshaped to ModelSpec + ProviderAuth with credential-based
  availability, replacing runner_type profiles and binary probing
type: decision
created: '2026-06-04T14:12:03Z'
modified: '2026-06-08T23:36:01Z'
related:
- 0152-koans-agent-layer-is-one-native-pydanticai.md
- 0008-three-tier-model-system-strongstandardcheap-over.md
---

koan's provider/model configuration in `koan/config.py` is built on `ModelSpec{provider, model, thinking, settings, caching}` together with `ProviderAuth` for credentials, replacing the earlier CLI-installation model: `ProfileTier` keyed on a `runner_type`, `AgentInstallation` records, and binary detection via `probe_all_runners`. Leon directed a big-bang reshape with no backwards compatibility, deleting the old schema outright rather than bridging it, because the credential model and the binary-installation model share no fields worth translating. Alternatives rejected: an auto-upgrader that rewrites old config files (carries dead schema for one-time value), and shipping the new profiles while making users re-pick their models (user friction with no durable benefit).

Provider availability was initially resolved from environment credentials -- `provider_available` over a `DEFAULT_PROVIDER_ENV_KEYS` map (for example, Gemini counted as available when `GOOGLE_API_KEY` or `GEMINI_API_KEY` was set), rather than by detecting an installed CLI binary. On 2026-06-07 this was superseded: provider keys moved into an encrypted `CredentialStore` (`koan/credentials.py`) persisted in `config.json`, `DEFAULT_PROVIDER_ENV_KEYS` was deleted, and availability now derives from `CredentialStore.has(provider)`. The env-var names survive only as `SEED_ENV_KEYS` in `koan/credentials.py`, used once to seed the store from the environment.

On 2026-06-08 this `ModelSpec` + `ProviderAuth` + `Profile` model was itself superseded by a clean-slate config-foundations reshape (`koan/config.py`, `koan/types.py`): `ProviderAuth`, `Profile`, and `ProfileTier` were deleted. Provider configuration is now a flat list of `connections` (credential plus endpoint settings), a global list of `configured_models` (each a connection + model-id pair), three role-slots (`strong`/`standard`/`cheap`) referencing configured-model ids, and a `presets` map with a reserved system entry `$last` plus an `active` pointer (named presets are a purely-additive future). `ModelSpec` survived as the resolved per-call model handed to the adapter, now carrying a `connection_id`. Credential availability moved from provider-type keys to per-connection keys, and the `SEED_ENV_KEYS` startup seeding was removed so credentials are entered manually.
