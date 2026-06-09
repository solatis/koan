---
title: koan provider API keys stored in an encrypted CredentialStore (Fernet + file
  master key), replacing os.environ reads
type: decision
created: '2026-06-07T07:54:27Z'
modified: '2026-06-08T23:36:12Z'
related:
- 0155-provider-config-reshaped-to-modelspec.md
- 0152-koans-agent-layer-is-one-native-pydanticai.md
- 0031-voyage-ai-as-sole-retrieval-provider-voyage-4.md
- 0127-static-shared-state-surfaces-via-projection.md
- 0181-koans-credentialstore-prunes-only-per-envelope.md
---

koan's credential handling (`koan/credentials.py`, `koan/config.py`, `koan/agents/adapter.py`, the `koan/memory/` subsystem) was reshaped so that all provider API keys live in an encrypted `CredentialStore` rather than being read from environment variables at runtime. Leon directed this on 2026-06-07. The store persists a `credentials` block in the user config -- one envelope per key, `{"scheme": "fernet", "ciphertext": <token>}` -- encrypted with Fernet (from the `cryptography` library) under a master key supplied by a pluggable `KeyBackend`. The only backend is `FileKeyBackend`, which auto-generates `~/.koan/master.key` (mode 0600) on first use and never regenerates it. `CredentialStore` decrypts every envelope into an in-memory cache at construction (logging and pruning an individually-undecryptable entry rather than crashing boot, while a systemic master-key failure instead leaves every envelope intact) and is the single credential authority for the process: the agent adapter resolves keys from it, and the memory subsystem reaches it through a module-level active store (`set_active_credential_store` / `active_credential_store`) because those modules have no `app_state`.

Keys are injected explicitly: `koan/agents/adapter.py:build_model` constructs `GoogleModel`/`AnthropicModel`/`OpenAIChatModel`/`BedrockConverseModel` with `provider=<Provider>(api_key=...)`, and the memory subsystem passes the key to its chat model and `voyageai.AsyncClient`. The secret value is never serialized onto the SSE projection wire or into HTTP responses -- only a boolean `available` (alongside non-secret endpoint settings) is exposed.

Rationale: Leon wanted keys stored internally and manageable through the settings interface, with the store as the authoritative source. Fernet was chosen over raw AES-256-GCM for misuse resistance (it manages the IV and authentication and emits a self-describing token). Explicit injection was chosen over an env-shim (decrypting keys back into `os.environ` at startup) because the shim keeps a covert global-env reliance and conflicts with the project's explicit-over-implicit preference. The file backend is acknowledged as deliberately low-security -- `master.key` is a plaintext key on disk and its loss makes all stored ciphertext unrecoverable -- and the `KeyBackend` seam exists so future backends (OS keychain, env-master, KMS) slot in without touching the store or its consumers. Alternatives rejected: base64-only encoding (no protection if the file leaks); an OS-keychain backend now (platform and headless friction); a single `KOAN_MASTER_KEY` env var (still an env dependency).

On 2026-06-08 the config-foundations reshape changed several specifics here while keeping the Fernet `CredentialStore` core intact: envelopes are keyed by `connection_id` rather than by provider type (a provider may have several connections); `seed_from_env` and the `SEED_ENV_KEYS` gap-fill were removed, so koan no longer reads `os.environ` for keys at all and credentials are entered manually; the persisted file moved from `~/.koan/config.json` (camelCase) to `~/.koan/config.yaml` (snake_case); and credential mutation moved from the unified `POST`/`DELETE /api/settings/provider` to the connection endpoints under `/api/config/connections`, which carry the secret and call `credential_store.set(connection_id, secret)`. Availability is now per-connection.
