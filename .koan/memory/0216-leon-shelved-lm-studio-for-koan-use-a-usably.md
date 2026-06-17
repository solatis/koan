---
title: 'Leon shelved and then removed LM Studio from koan: usably-loaded local models
  are too resource-heavy on his hardware'
type: context
created: '2026-06-13T10:27:51Z'
modified: '2026-06-14T10:06:28Z'
related:
- 0218-koan-removed-lmstudio-support-but-retained-the.md
- 0198-live-llm-integration-tests-target-a-local-openai.md
---

While hardening koan's LM Studio context handling, Leon terminated his LM Studio server and concluded LM Studio is impractical for his use: once a model is loaded with a genuinely usable context window (rather than the 4096-token default), the qwen3.6-35b-a3b model consumes too many system resources to be practical on his hardware. Acting on this, koan then removed the `lmstudio` provider entirely -- the provider type, the OpenAI-compat dialect branches, the native /api/v0 context-overflow probe, and the live e2e test were deleted -- while retaining the generic keyless-local provider seam dormant (an emptied `KEYLESS_PROVIDER_TYPES` and `LOCAL_PROVIDERS`) so a local provider can be re-added later as a data change. This matters because LM-Studio-specific behavior is no longer part of koan, and Leon may re-add local-model support "in a different way" rather than restoring the removed integration.
