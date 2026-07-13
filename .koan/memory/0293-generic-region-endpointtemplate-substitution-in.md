---
title: "Generic {region} endpoint_template substitution in adapter \u2014 route-data\
  \ plumbing that enables regional endpoint routes without dialect code"
type: decision
created: '2026-07-13T08:29:54Z'
modified: '2026-07-13T08:29:54Z'
related:
- 0155-provider-config-reshaped-to-modelspec.md
- 0201-aws-bedrock-requires-a-stored-long-lived-api-key.md
- 0252-koan-added-the-ollama-cloud-provider.md
---

koan's provider adapter (`koan/agents/adapter.py`, `build_model`) — when `base_url` is `None` and the route's `endpoint_template` in `koan/models/routes.py` contains `{region}`, the adapter substitutes the connection's locality (`effective_region`) into the template to construct the `base_url`. This is generic logic: it checks whether the template string contains `{region}`, not which route ID or dialect is in play. It applies to any route whose `endpoint_template` contains `{region}`. When the template requires a region but no locality is set, it raises `AgentError(code='missing_region')`. This pattern enabled the `bedrock-mantle` route to be added as pure data — one route registry entry (dialect=`anthropic-messages`, auth=`bearer`, `endpoint_template="https://bedrock-mantle.{region}.api.aws/anthropic"`), one codec (`BedrockMantleCodec` in `koan/models/codecs.py` that strips the `anthropic.` prefix and delegates to `AnthropicCodec`), and one capability overlay row in `koan/models/capabilities.py` — with zero new code in `koan/agents/dialects.py`. The falsification criterion ("if any new dialect code is needed, stop and report") was satisfied. Rationale: template substitution is route-data plumbing, not dialect code. The ollama-cloud route already reads `route.endpoint_template` for its fixed endpoint; generalizing to `{region}` substitution covers regional endpoints without per-route adapter branching. Alternatives rejected: route-ID-specific branching in the adapter for bedrock-mantle — rejected because it violates the falsification criterion and creates a per-route maintenance burden. Constructing the base_url in the codec — rejected because the codec's job is wire-ID translation, not endpoint construction; the adapter is the natural home for provider construction parameters. Decision surfaced when designing the bedrock-mantle route; the user confirmed that template substitution from route data is allowed plumbing, not dialect code.
