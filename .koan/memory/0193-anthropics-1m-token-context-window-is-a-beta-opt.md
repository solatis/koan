---
title: Anthropic's 1M-token context window is a beta opt-in header, not a separate
  model id or a PydanticAI profile field
type: context
created: '2026-06-08T23:35:52Z'
modified: '2026-06-08T23:35:52Z'
related:
- 0172-usage-cost-and-context-window-percent-are-derived.md
---

Anthropic's 1-million-token context window for Claude is enabled by a beta opt-in (a context-management beta header on the request), not by selecting a distinct model id and not via any field on PydanticAI's `ModelProfile`. This was verified while designing koan's capability resolution. It matters because koan cannot infer the 1M variant from the model id or read it from the profile: koan sources context-window size and its variants itself (`koan/agents/model_catalog.py`) and models a variant like 1M as a capability-gated setting on the resolved capabilities, surfaced only for the (provider, model) pairs that support it. An agent looking for the 1M context in the model-id string or the profile will not find it.
