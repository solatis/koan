---
title: AWS Bedrock requires a stored long-lived API key in koan; the AWS credential
  provider chain was dropped
type: decision
created: '2026-06-11T02:49:34Z'
modified: '2026-06-11T02:49:34Z'
related:
- 0182-non-secret-provider-settings-region-baseurl-flow.md
- 0178-koan-provider-api-keys-stored-in-an-encrypted.md
- 0184-local-ai-lm-studio-support-keyless-openai.md
---

koan's Bedrock authentication (`koan/agents/adapter.py:build_model`, the `/api/config/connections` endpoints in `koan/web/app.py`, and the bedrock case of `frontend/src/components/molecules/ConnectionForm.tsx`) requires a stored long-lived Bedrock API key; the AWS credential provider chain (env vars, shared profile, IAM role) is not used. The user directed this on 2026-06-11, stating the credential chain "is not good enough." `build_model`'s bedrock branch raises `AgentError(code="missing_credentials")` when `api_key` is None (after the existing `missing_region` check) and threads the key into `BedrockProvider(region_name=..., api_key=..., base_url=...)`, which consumes it as a boto3 bearer-token session; region is still required. The connection form gained a required API-key field for the bedrock type; the secret is stored in the encrypted Fernet `CredentialStore` keyed by connection id like other keyed providers, so per-connection availability and the start-run credential gate (already `store.has(connection_id)`) mark a keyless bedrock connection unavailable and unrunnable. Alternative rejected: an optional Bedrock API key with the credential chain retained as fallback and region-derived availability -- rejected because the user wanted the key required, not merely additive. This removed the earlier keyless-with-region path in which bedrock was built as `BedrockProvider(region_name=region)` with no api_key.
