---
title: Non-secret provider settings (region, base_url) flow through resolve_provider_auth
  into explicit model construction; carried on Connection after ProviderAuth deletion
type: decision
created: '2026-06-07T14:24:46Z'
modified: '2026-06-08T23:36:21Z'
related:
- 0155-provider-config-reshaped-to-modelspec.md
- 0178-koan-provider-api-keys-stored-in-an-encrypted.md
- 0179-pydantic-ai-infermodel-reads-osenviron-for-the.md
---

Leon directed that koan manage provider credentials and their non-secret settings internally and from the web UI. To carry the non-secret half, `koan/agents/adapter.py` was extended so the previously defined-but-unread `ProviderAuth` (fields `provider`, `region`, `base_url` in `koan/types.py`) became a live read authority, kept separate from the encrypted secret in `CredentialStore`. A pure resolver `resolve_provider_auth` joins the decrypted API key (from the store) with the matching non-secret `region`/`base_url` into a `ResolvedProviderAuth` bundle that `koan/agents/pydantic_ai.py` passes to `build_model(spec, api_key, region, base_url)`. `build_model` threads `region_name` and `base_url` into the explicit provider constructors -- `BedrockProvider(region_name=..., api_key=..., base_url=...)`, and `base_url` into `OpenAIProvider`/`AnthropicProvider`; `GoogleProvider` receives neither. Bedrock requires an explicitly-configured region and raises `AgentError(code="missing_region")` when none is present; a silent fallback to an AWS-environment default region was rejected as non-deterministic and non-observable. The `infer_model(f"{provider}:{model}")` fallback was removed entirely, so even keyless bedrock is built explicitly as `BedrockProvider(region_name=region)` and no construction path can fall back to a hidden `os.environ` key read. Alternatives rejected: storing `region`/`base_url` inside the encrypted Fernet envelope (couples non-secret config to ciphertext and blocks the UI from displaying it without decryption); threading the region through a process global or side channel (hidden coupling, untestable). The secret/non-secret split is the load-bearing seam -- only the API key is ciphertext; everything displayable is plaintext.

On 2026-06-08 the config-foundations reshape deleted `ProviderAuth`: its non-secret fields (`region`, `base_url`, plus Azure deployment/api_version and timeout) moved onto the `Connection` type, and `resolve_provider_auth(connection, store)` now joins a connection's stored secret with its endpoint settings into the same `ResolvedProviderAuth` bundle. The rest of this entry still holds -- the secret/non-secret split, explicit `build_model` construction with no `infer_model` fallback, and Bedrock raising on a missing region -- only the carrier of the non-secret settings changed from a separate `ProviderAuth` list to the connection itself.
