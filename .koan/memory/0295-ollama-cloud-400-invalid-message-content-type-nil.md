---
title: 'Ollama Cloud 400 ''invalid message content type: <nil>'': always-on server-side
  thinking plus pydantic-ai''s retry replaying an empty assistant message as content
  null'
type: lesson
created: '2026-07-14T10:35:10Z'
modified: '2026-07-14T10:35:10Z'
related:
- 0171-model-thinking-is-a-portable-koan-thinkingmode.md
- 0228-koan-retries-transient-provider-errors-at-the.md
- 0252-koan-added-the-ollama-cloud-provider-key-required.md
---

Mechanical memory query generation (cheap slot, deepseek-v4-flash:cloud, thinking=disabled) failed mid-run with HTTP 400 'invalid message content type: <nil>' from Ollama Cloud's /v1 endpoint. The 400 reads like a malformed-request bug but is a three-step interaction:

1. Ollama Cloud serves several models (deepseek-v4-flash among them) with server-side thinking ALWAYS ON. koan's D4 semantics map thinking='disabled' to omitting the setting entirely -- which leaves Ollama's thinking on. The model can then return its ENTIRE answer in the OpenAI-compat 'reasoning' field with content='' (content-dependent: a task text discussing thinking modes triggered it deterministically; generic prompts usually do not, so smoke tests pass while specific user tasks fail).
2. pydantic-ai's output validation sees empty text output and issues a retry ('Please return text.'), replaying the conversation.
3. The replayed assistant message (reasoning-only, no TextPart) serializes as 'content': null. OpenAI's API accepts null assistant content; Ollama rejects it: 400 'invalid message content type: <nil>'. The retry can therefore never succeed.

Fix: emit_reasoning_off(route_id, mode) in koan/agents/dialects.py, applied in build_resolved_model (registry.py) -- when mode='disabled' AND route is ollama-cloud, emit pydantic-ai setting openai_reasoning_effort='none'. Probing established that reasoning_effort='none' is the ONLY /v1 switch Ollama honors for this ('think': false is silently ignored). The override is keyed on ROUTE ID, not dialect: ollama-cloud shares the openai-chat dialect with openai/openrouter, and OpenAI rejects reasoning_effort on non-reasoning models, so a dialect-scoped emission would break OpenAI routes.

Residual risk: thinking-ENABLED Ollama models (e.g. glm orchestrator slots) can still hit the null-content replay whenever a response comes back reasoning-only -- that is a pydantic-ai/Ollama incompatibility to fix upstream (assistant content should serialize as '' not null for Ollama). Recognize it by the same 400 body appearing in the retry-loop error summaries.

Diagnosis technique that cracked it: an httpx event-hook client injected via a monkeypatched adapter.build_model, dumping the exact wire request/response -- the request showed messages=[system, user, assistant(content=null, reasoning=...), user('Validation feedback: Please return text.')], which named all three actors at once.
