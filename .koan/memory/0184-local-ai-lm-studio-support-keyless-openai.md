---
title: 'Local AI / LM Studio support: keyless OpenAI-compatible provider plus a dynamic
  per-provider model overlay (selectable list later moved to live-on-query)'
type: decision
created: '2026-06-08T01:31:02Z'
modified: '2026-06-08T23:36:31Z'
related:
- 0155-provider-config-reshaped-to-modelspec.md
- 0182-non-secret-provider-settings-region-baseurl-flow.md
- 0183-koan-does-not-validate-provider-api-keys-on-save.md
---

koan's provider/model subsystem (`koan/agents/adapter.py`, `koan/agents/model_listing.py`, `koan/credentials.py`, `koan/projections.py`, `koan/web/app.py`) gained local-AI support via LM Studio plus live per-provider model-list retrieval. Leon directed this and resolved the design forks (augment vs replace, listing scope, validation model) through clarifying questions.

LM Studio is keyless and OpenAI-compatible. It is enumerated via a `LOCAL_PROVIDERS` map in `koan/credentials.py` (provider -> default base_url, e.g. lmstudio -> http://localhost:1234/v1). `build_model` constructs it through the existing OpenAI path (`OpenAIChatModel` + `OpenAIProvider`) with the configured `base_url` and a non-empty placeholder api_key (the OpenAI SDK rejects an empty key even though LM Studio ignores it). LM Studio models are never added to `MODEL_CAPABILITIES` or `PROVIDER_ID_MAP`; their cost resolves to 0 via the existing `price_for_usage` try/except guard in the projection fold, preserving fold determinism.

Live model lists for the listing-capable providers are retrieved by `koan/agents/model_listing.py` and stored as a per-provider overlay (`provider_models` on `ProviderConfigState`), surfaced to the browser through a `Settings.provider_models` projection field, delivered via the projection-Settings channel rather than a new HTTP read endpoint. The overlay is refreshed eagerly at startup by a non-blocking background task and on each Test/save; model-listing network calls are never placed inside the projection fold or inside the boot-time provider-availability refresh (which must stay network-free).

Listing scope is LM Studio + OpenAI + Anthropic + Google. Bedrock is excluded because pydantic-ai exposes no unified model-listing API and the boto3 client it surfaces is `bedrock-runtime` (data plane), which has no list operation -- listing Bedrock foundation models requires a separate control-plane `bedrock` client plus the `bedrock:ListFoundationModels` IAM permission, judged a disproportionate lift.

On 2026-06-08 the config-foundations reshape changed two claims here. First, the selectable model list is no longer sourced from the static `MODEL_CAPABILITIES` catalog: it is fetched live per connection on demand (`list_models_for_connection`) with free-text fallback, and there is no bundled baseline the user selects from; the genai-prices/`model_catalog` snapshot remains only for pricing and context-window facts. Second, profile-tier validation was removed entirely because the `Profile`/`ProfileTier` types were deleted (configuration is now connections + configured-models + role-slots). LM Studio keyless support persists, but its availability now derives from a `base_url` on a `Connection` rather than on a `ProviderAuth` entry.
