---
title: koan provider/model config layered as flat connections + global configured-models
  + strong/standard/cheap role-slots + a presets map with a reserved $last entry
type: decision
created: '2026-06-08T23:35:29Z'
modified: '2026-06-08T23:35:29Z'
related:
- 0155-provider-config-reshaped-to-modelspec.md
- 0008-three-tier-model-system-strongstandardcheap-over.md
---

koan's user-facing model configuration (`koan/config.py`, `koan/types.py`) is layered into four concerns: a flat list of `connections` (each a credential plus endpoint settings -- base_url, AWS region, Azure deployment/api_version, timeout -- where Anthropic-direct, Bedrock, OpenAI, and LM Studio are peers); a global list of `configured_models`, each a (connection, model-id) pair, so the same model family reached through two providers is two distinct configured models; three role-slots (`strong`, `standard`, `cheap`) that each reference one configured-model id with no eligibility rules; and persistence as a `presets` map plus an `active` pointer, where today the map holds exactly one reserved system entry `$last` (overwritten whenever the active config changes) and `active` always points at it. Leon directed this to replace the previous `Profile` model (a named bundle of a strong/standard/cheap triple plus separately-configured `ProviderAuth` credentials). Rationale: profiles conflated the active configuration with a reusable saved bundle; they assumed koan could ship sensible default profiles, but koan is local and does not control which providers a user has; and most users configure once and never revisit, so profiles made the common path heavier than necessary. The schema was shaped so named presets are purely additive later -- pointer separate from store, `$`-prefixed keys reserved for the system (user names may not start with `$`), named entries needing no migration. Alternatives rejected: keeping profiles (the conflation); building named-preset management now (out of scope -- only `$last`, no creation UI); a floating request-time 'latest' pointer (koan pins versions instead). Connection/endpoint settings live on the connection, never on the model.
