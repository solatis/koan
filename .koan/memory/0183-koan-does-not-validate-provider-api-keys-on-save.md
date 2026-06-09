---
title: koan does not validate provider API keys on save; validation is a separate
  manual free model-list 'Test connection' action
type: decision
created: '2026-06-07T14:24:57Z'
modified: '2026-06-08T01:31:11Z'
related:
- 0155-provider-config-reshaped-to-modelspec.md
- 0178-koan-provider-api-keys-stored-in-an-encrypted.md
---

When koan gained a web UI for managing provider credentials, Leon decided the provider settings flow performs no validation of a key on save -- neither a local model-construction check nor a live API probe -- and the existing `POST /api/settings/validate-provider` route plus its `api_validate_provider` handler in `koan/web/app.py` were deleted rather than kept. Saving a credential through `POST /api/settings/provider` simply encrypts and stores it; correctness is assumed. Rationale, stated by Leon when the credential-management UI was scoped: a live test incurs a network round-trip and a token/credit charge on every save, and a local presence/constructability check adds surface for weak assurance, so both were judged not worth it and deferred as possible future work. Alternatives rejected: keeping the local construction check (assurance too weak to justify it); adding a live 'test connection' probe (per-save cost and latency). The absence of credential validation on save is therefore deliberate -- a deferred cost trade-off, not an oversight.

Leon subsequently directed reintroducing the deferred 'test connection' capability, reframed to avoid the original cost objection. A separate, user-triggered endpoint `POST /api/settings/provider/test` (handler `api_settings_provider_test`) validates a provider by retrieving its model list -- a free call, not a completion, so no token/credit charge. It is driven by a 'Test connection' button in the settings Providers card and validates the candidate values currently in the form (falling back to stored values), returning HTTP 200 `{ok, count, models}` on success or `{ok: false, message}` on failure so the UI renders a green/red result. The save path itself is unchanged and still stores credentials without validation. The distinction is deliberate: validation is explicit, manual, and free, never the automatic per-save completion probe that the original decision rejected. For keyless providers (LM Studio) the same call validates connectivity rather than an auth token; providers without a model-list path (bedrock, voyage) have no Test action.
