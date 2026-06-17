---
title: koan added the openrouter provider as a key-requiring OpenAI-protocol provider
  with minimal capability fidelity for its namespaced models
type: decision
created: '2026-06-14T10:05:15Z'
modified: '2026-06-14T10:05:15Z'
related:
- 0184-local-ai-lm-studio-support-keyless-openai.md
---

koan's provider subsystem (koan/types.py, koan/agents/adapter.py, koan/agents/model_listing.py, koan/agents/model_catalog.py, koan/web/app.py) gained the `openrouter` provider type; Leon directed adding it to reach a large number of models. openrouter is key-requiring (an OPENROUTER_API_KEY in the CredentialStore) and OpenAI-protocol-compatible; build_model constructs it through pydantic-ai's `OpenRouterModel` + `OpenRouterProvider(api_key=...)`, which fixes the base_url to https://openrouter.ai/api/v1 (so openrouter exposes no per-connection base_url field), and its ids are namespaced `vendor/model` (e.g. anthropic/claude-3.5-sonnet). Live listing reuses the shared OpenAI-compatible `/v1/models` path; the listing-capable set is openai/anthropic/google/openrouter (bedrock has no unified list API, voyage is embedding-only). Cost resolves via a `PROVIDER_ID_MAP` "openrouter"->"openrouter" entry against the genai-prices bundled snapshot, which carries openrouter and resolves the namespaced ids (with name=None, so display falls back to the id). Leon chose MINIMAL capability fidelity: openrouter gets no branch in capability_resolver, recognition, or adapter.map_thinking, so its models degrade to conservative defaults (recognized=False, thinking_modes=[]) and koan offers no thinking-mode control for them. Rationale: openrouter exposes 500+ models, making per-model curation in MODEL_CAPABILITIES infeasible. Alternative rejected: full capability resolution (routing through OpenRouterProvider.model_profile, which parses vendor/model and force-enables thinking, plus teaching the recognition parser to split namespaced ids) -- judged not worth the cost. The roughly 600-entry live list is handled at the UI rendering layer (the model chooser caps mounted rows), not by server-side curation, keeping the full live list intact.
