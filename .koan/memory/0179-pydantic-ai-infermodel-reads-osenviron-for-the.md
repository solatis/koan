---
title: pydantic-ai infer_model() reads os.environ for the API key itself; koan's resolve_credentials
  was validation-only
type: lesson
created: '2026-06-07T07:54:40Z'
modified: '2026-06-07T14:25:35Z'
related:
- 0152-koans-agent-layer-is-one-native-pydanticai.md
- 0164-plan-built-on-the-pydanticai-v2-beta-assumed-its.md
- 0182-non-secret-provider-settings-region-baseurl-flow.md
---

During the move of koan's provider credentials out of environment variables into an encrypted `CredentialStore`, the agent path turned out to depend on a hidden env read: `koan/agents/adapter.py:build_model` constructed models with `infer_model(f"{prefix}:{model}")`, and pydantic-ai's `infer_model` resolves the provider's API key from `os.environ` itself at call time. koan's own `resolve_credentials` had been validation-only -- it returned an `api_key` that no caller ever threaded into the model -- so simply storing keys internally would not have changed where the key actually came from. The fix was to build provider models explicitly (`GoogleModel`/`AnthropicModel`/`OpenAIChatModel`/`BedrockConverseModel` with `provider=<Provider>(api_key=...)`). The same hazard recurred in a subtler form: a `build_model` fallback to `infer_model` whenever `api_key` was `None` would silently re-introduce the `os.environ` path and defeat the store-only goal. It was first narrowed so a key-requiring provider with no stored credential raises a clear error, and subsequently the `infer_model` fallback was removed entirely -- `build_model` now builds every provider explicitly, constructing even keyless bedrock as `BedrockProvider(region_name=region)`, so no construction path remains that falls back to an env-resolving constructor. Root cause: a convenience abstraction (the `"{provider}:{model}"` string form of `infer_model`) performs an `os.environ` credential read internally, so an audit limited to koan's own `os.environ` calls misses it. Prevention: when migrating credentials off environment variables, inject keys explicitly into each provider/client constructor and confirm there is no remaining fallback to an env-resolving constructor; check the third-party client APIs for internal env reads, not only the project's own code.
