---
title: 'LM Studio ''Test connection'' returned 0 models: a single-type allowlist over
  a provider model catalog silently drops valid chat-capable model types'
type: lesson
created: '2026-06-11T10:09:47Z'
modified: '2026-06-11T10:09:47Z'
related:
- 0184-local-ai-lm-studio-support-keyless-openai.md
---

koan's live model listing (`koan/agents/model_listing.py`) reported 0 models for a working LM Studio connection: the settings 'Test connection' action showed a green '0 models' badge while `GET http://localhost:1234/v1/models` returned three models live. Root cause: the LM Studio listing helper queried the native `/api/v0/models` endpoint and kept only entries whose `type` field equaled `'llm'`. LM Studio tags multimodal chat models as `vlm` (e.g. `qwen/qwen3.6-35b-a3b`, a Qwen3.6 model) and embedding models as `embeddings`, so the single-value allowlist matched nothing and returned an empty list -- delivered as a SUCCESS response (`{ok: true, count: 0}`), which masked the filtering bug as a benign 'no models loaded' state.

Prevention: filter a provider's model catalog down to chat/completion models with an EXCLUSION denylist (drop ids containing embedding/whisper/tts/etc.), not a positive allowlist of one model-type value -- an allowlist cannot anticipate valid-but-unlisted types a provider may report (`vlm`, and future types). Also treat a provider listing that returns zero results AS a success as a filtering-bug smell worth checking against the raw provider response, since the empty-but-ok shape hides the defect. The fix shared the OpenAI path's id-substring denylist (`_is_chat_model_id`) across the openai and lmstudio listing paths.
