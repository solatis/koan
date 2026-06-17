---
title: koan removed lmstudio support but retained the keyless-local provider seam
  dormant for a future re-add
type: decision
created: '2026-06-14T10:05:36Z'
modified: '2026-06-14T10:05:36Z'
related:
- 0216-leon-shelved-lm-studio-for-koan-use-a-usably.md
- 0186-koan-defaults-to-hard-cutover-no-backwards.md
---

koan removed the `lmstudio` provider entirely -- the provider type, the OpenAI-compat dialect branches, the native /api/v0 loaded-context overflow probe (the former koan/agents/lmstudio_native.py and the proactive/reactive handling in koan/agents/pydantic_ai.py), the live e2e test, the frontend provider entries, and the docs. Leon directed the removal because usably-loaded local models are too resource-heavy on his hardware and may be re-added later "in a different way." Decision (Leon-directed): rather than a full hard cutover of the keyless machinery, the generic keyless-local seam is retained DORMANT. `KEYLESS_PROVIDER_TYPES` (koan/types.py) is emptied to `frozenset()` and `LOCAL_PROVIDERS` (koan/credentials.py) to `{}` -- both kept with explanatory comments; the adapter build/listing keyless branches were generalized from the hardcoded "lmstudio" string onto `provider in KEYLESS_PROVIDER_TYPES` membership (unreachable while the set is empty); and the `if conn.type in KEYLESS_PROVIDER_TYPES` seams in koan/web/app.py remain. A future local-provider re-add is therefore a DATA change (add the type to KEYLESS_PROVIDER_TYPES and ProviderType, supply a base_url default in LOCAL_PROVIDERS), not a code rewrite -- a deliberate exception to koan's hard-cutover-by-default policy. No config migration was added: a user whose ~/.koan/config.yaml still binds slots to lmstudio clears it themselves, and app boot stays safe because the dormant keyless seams and the eager model-list refresh skip an unbuildable connection rather than crashing.
