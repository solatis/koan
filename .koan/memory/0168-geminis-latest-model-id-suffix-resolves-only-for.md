---
title: 'Gemini''s -latest model-id suffix resolves only for unversioned names: gemini-2.5-pro-latest
  404s, use gemini-2.5-pro'
type: lesson
created: '2026-06-04T14:20:19Z'
modified: '2026-06-04T14:20:19Z'
related:
- 0152-koans-agent-layer-is-one-native-pydanticai.md
- 0155-provider-config-reshaped-to-modelspec.md
---

On Google/Gemini, the `-latest` model-id suffix resolves only for unversioned model names: `gemini-flash-latest` is valid, but appending `-latest` to an already-versioned name such as `gemini-2.5-pro` produces `gemini-2.5-pro-latest`, which returns a 404 from the provider. The versioned id is used bare: `gemini-2.5-pro`. Root cause: the `-latest` alias is defined only for unversioned family names, not as a general suffix. This 404 blocked live Gemini runs until the id was corrected; it is the kind of provider-specific model-id rule that stays invisible until a live call fails.
