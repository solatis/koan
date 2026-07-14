---
title: Ollama cloud models with single ("medium",) thinking mode are always-on server-side;
  pydantic-ai never propagates thinking mode to ollama cloud models
type: context
created: '2026-07-14T12:02:56Z'
modified: '2026-07-14T12:02:56Z'
related:
- 0252-ollama-cloud-provider.md
- 0295-ollama-cloud-400-nil-content.md
- 0171-model-thinking-is-portable.md
---

The ollama-cloud provider's models in koan's `_BASE_CATALOG` (`koan/models/capabilities.py`) fall into two thinking categories: always-on models with a single `("medium",)` thinking mode (e.g. glm-5.2, deepseek-flash-4, minimax-m2.5, qwen-3.5) and discrete-effort models with multi-mode thinking (e.g. gpt-oss, deepseek-pro with `("low", "medium", "high")`). The always-on models have server-side thinking permanently enabled — the `("medium",)` entry in the catalog is descriptive, not controllable. koan's `adapter.map_thinking` (`koan/agents/adapter.py`) has no ollama-cloud branch, so pydantic-ai never propagates any `ThinkingMode` setting to ollama cloud models regardless of what the user selects. The backend already handles the disabled case via `emit_reasoning_off` in `koan/agents/dialects.py`, which emits `openai_reasoning_effort='none'` when `mode='disabled'` and the route is ollama-cloud. This matters because the frontend thinking selector is non-functional for always-on models — the user's selection has no effect on actual model behavior, so the selector should be disabled rather than presented as a live control.
