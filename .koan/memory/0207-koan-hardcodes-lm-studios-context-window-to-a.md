---
title: koan replaced the hardcoded LM Studio 262144 context-window default with an
  explicit per-ConfiguredModel context_window override (require-explicit)
type: decision
created: '2026-06-11T13:11:31Z'
modified: '2026-06-11T23:28:56Z'
related:
- 0184-local-ai-lm-studio-support-keyless-openai.md
- 0172-usage-cost-and-context-window-percent-are-derived.md
- 0190-koan-resolves-model-capabilities-by-wrapping.md
---

koan's model context-window resolution (`koan/agents/model_catalog.py`, `koan/agents/registry.py`, `koan/web/app.py`, `koan/projections.py`, `koan/types.py`, `koan/config.py`) gained an explicit, user-supplied per-model context window. Leon directed it after observing that a single provider-wide hardcode cannot represent the true window of whatever model LM Studio currently has loaded.

The mechanism: `ConfiguredModel` (the global `(connection, model_id)` config entity) carries an optional `context_window: int | None`. In `registry.resolve_model_spec` this explicit value is top precedence -- above the variant-gated `SlotAssignment.context_window` (honored only when it matches an advertised `caps.context_window_variants`) and above the `caps`/`context_window_for` fallback -- so it never activates unless the user sets it. It is surfaced raw to the frontend on the `configured_models_listed` projection event (the Settings form pre-fills from it) and overrides `caps.context_window` in the `model_capabilities_listed` capability display, so the header gauge and Settings display reflect the configured value. It is written via the existing `POST /api/config/models` command plus a numeric input added to the `RoleRow` Settings control, and round-trips through `~/.koan/config.yaml` and the frozen per-run `run-config.yaml`.

Concurrently the earlier provider-wide stopgap was deleted as a hard cutover with no compatibility shim: the module-level `LMSTUDIO_DEFAULT_CONTEXT_WINDOW = 262144` (256 * 1024) constant in `model_catalog.py`, its `if provider == "lmstudio"` short-circuit in `context_window_for()`, and the matching stamp in `_list_openai_compatible_models()` are all gone. As a result `context_window_for("lmstudio", ...)` now returns 0 and the model listing stamps 0, so an unconfigured LM Studio model suppresses the header context gauge (the projection fold computes `context_window_percent` only when the window is > 0) and shows an empty capability window until the user supplies an explicit value. Leon chose this require-explicit behavior over keeping 262144 as an unset-fallback, because the single provider-wide constant over-reported every smaller model loaded in LM Studio.

Durable facts that did not change: LM Studio's OpenAI-compatible `/v1/models` endpoint carries no context-length field, and LM Studio is deliberately absent from `MODEL_CAPABILITIES`, `PROVIDER_ID_MAP`, and the genai-prices snapshot (so its cost still resolves to 0). The context window remains a koan-internal reporting/derivation value only -- koan sends nothing about context length to the LM Studio server, because the `OpenAIChatModel` chat-completions path has no parameter to set the server's loaded context.

Alternatives rejected: keeping the 262144 provider-wide default as an unset-fallback (over-reports smaller models, the bug this change fixes); placing the override on the `Connection` (one window per server, too coarse when a connection serves several models) or on the per-use-site `MemoryBinding`/`SlotAssignment` fields only (narrower reach and duplicated config than the shared `ConfiguredModel` home, and the memory-LLM path has no runtime gauge to consume it).
