# Provider adapter: the single per-provider dialect seam.
# Covers all four day-one providers (M7): google, anthropic, openai, bedrock.
# Built against the installed pydantic-ai 2.0.0b6 API.
#
# Responsibilities:
#   - provider_available: check credential presence in CredentialStore
#   - map_thinking: translate koan ThinkingMode to provider-specific settings
#   - build_model_settings: merge spec settings with thinking + caching
#   - build_model: construct a pydantic-ai Model object from a ModelSpec +
#     an explicit api_key (never reads os.environ)
#
# resolve_credentials (env-based) and DEFAULT_PROVIDER_ENV_KEYS were removed
# in the credential-store migration.  M1: resolve_provider_auth now takes a
# Connection instead of a provider string; SEED_ENV_KEYS removed (brief D13).

from __future__ import annotations

from dataclasses import dataclass

from ..agents.base import AgentDiagnostic, AgentError
from ..types import Connection, ModelSpec, ResolvedCapabilities, ThinkingMode


@dataclass
class ResolvedProviderAuth:
    """In-memory join of a provider's decrypted secret and its non-secret settings.

    Produced by resolve_provider_auth; consumed by build_model. Never persisted
    or transmitted -- it exists only for the duration of a model-build call.
    """

    api_key: str | None
    region: str | None
    base_url: str | None

# Thinking token budget by ThinkingMode -- shared by the budget-based providers
# (google google_thinking_config, anthropic anthropic_thinking).
_THINKING_BUDGET: dict[ThinkingMode, int | None] = {
    "disabled": None,
    "low":      512,
    "medium":   2048,
    "high":     8192,
    "xhigh":    16384,
    "max":      32768,
}

# OpenAI exposes reasoning as a coarse effort knob, not a token budget.
_OPENAI_EFFORT: dict[ThinkingMode, str | None] = {
    "disabled": None,
    "low":      "low",
    "medium":   "medium",
    "high":     "high",
    "xhigh":    "high",
    "max":      "high",
}

# koan provider name -> pydantic-ai provider prefix (used to validate known providers).
# openrouter uses the library's dedicated OpenRouterModel/OpenRouterProvider (key-required,
# library-fixed endpoint).
_PROVIDER_PREFIX: dict[str, str] = {
    "google":      "google",
    "anthropic":   "anthropic",
    "openai":      "openai",
    "bedrock":     "bedrock",
    "openrouter":  "openrouter",
}

# Providers that require an explicit API key (as opposed to bedrock which
# can authenticate via AWS profile/SSO without a bearer token).
# When api_key is None for a key-requiring provider, build_model raises
# missing_credentials rather than silently falling back to os.environ.
# This set is documentation/guard-only: build_model uses explicit branches +
# a fall-through for credential enforcement, not this set directly.
_KEY_REQUIRING_PROVIDERS = {"google", "anthropic", "openai", "openrouter"}


def provider_available(provider: str, store: "CredentialStore | None" = None) -> bool:
    """True when the credential store has a secret for the provider.

    The store is the sole credential authority; availability is no longer
    derived from os.environ. Returns False when store is None (e.g. in tests
    that do not set up a credential store).
    """
    return bool(store and store.has(provider))


def resolve_provider_auth(
    connection: "Connection | None",
    store: "CredentialStore | None",
) -> ResolvedProviderAuth:
    """Join the decrypted secret with endpoint settings from a Connection.

    Resolves api_key from the credential store by connection id (store is the
    only permitted source for api_key -- os.environ is never read here).
    region and base_url come directly from the Connection fields.
    Returns None for each absent value; never raises on missing data.
    connection may be None for pre-M1 ModelSpecs (no connection_id); all
    fields return None in that case.
    """
    if connection is None:
        return ResolvedProviderAuth(api_key=None, region=None, base_url=None)
    api_key = store.resolve(connection.id) if store else None
    return ResolvedProviderAuth(
        api_key=api_key,
        region=connection.region,
        base_url=connection.base_url,
    )


def map_thinking(provider: str, caps: "ResolvedCapabilities", mode: ThinkingMode) -> dict:
    """Map koan ThinkingMode to the provider's model_settings dict (capability-driven).

    Dispatches on `provider` for the SETTING KEY but chooses the VALUE/shape
    from `caps.thinking_shape` (brief D4/D5 wrap-and-extend):
      - "budget"   -> discrete token budget via _THINKING_BUDGET
      - "adaptive" -> Anthropic adaptive form (no explicit budget, newer models)
      - "effort"   -> named effort string via _OPENAI_EFFORT (OpenAI reasoning)
      - "none"     -> {} (provider has no thinking knob)

    Returns {} when mode is "disabled" or not in caps.thinking_modes, so the
    caller never needs to special-case the disabled path.

    - google:    google_thinking_config with thinking_budget; pydantic_ai maps
                 this to thinking_level for Gemini 3+ models internally.
    - anthropic: anthropic_thinking {type: enabled, budget_tokens: N}
                 or {type: adaptive} for adaptive-capable models.
    - openai:    openai_reasoning_effort effort_string.
    - bedrock:   no-op (thinking is driven by the underlying model profile).
    - unknown:   {} (graceful fallthrough per brief D5).
    """
    # Disabled or unsupported mode: nothing to emit.
    if mode == "disabled" or mode not in caps.thinking_modes:
        return {}

    if provider == "google":
        budget = _THINKING_BUDGET.get(mode, 2048)
        return {"google_thinking_config": {"thinking_budget": budget, "include_thoughts": True}}

    if provider == "anthropic":
        if caps.thinking_shape == "adaptive":
            # Adaptive thinking: no explicit budget; pydantic_ai passes the
            # {"type": "adaptive"} form which the API translates to its own budget.
            return {"anthropic_thinking": {"type": "adaptive"}}
        # Budget shape (older anthropic models and bedrock-anthropic).
        budget = _THINKING_BUDGET.get(mode) or 2048
        return {"anthropic_thinking": {"type": "enabled", "budget_tokens": budget}}

    if provider == "openai":
        effort = _OPENAI_EFFORT.get(mode)
        if effort is None:
            return {}
        return {"openai_reasoning_effort": effort}

    if provider == "bedrock":
        # Bedrock: thinking controlled by the underlying model profile inside
        # pydantic_ai's BedrockConverseModel; no portable koan-level knob.
        return {}

    # Graceful fallthrough for unrecognized providers (brief D5).
    return {}


def _caching_settings(spec: ModelSpec, caps: "ResolvedCapabilities") -> dict:
    """Resolve the CachingPolicy into provider-specific cache settings.

    Gates on caps.supports_prompt_caching (capability-driven, brief D4/D5) rather
    than a hardcoded provider check.  Currently only anthropic exposes explicit
    cache-control settings; google/openai cache automatically server-side.

    Returns {} when caching is off, or when the model does not support
    explicit prompt caching.
    """
    if spec.caching.mode == "off":
        return {}
    if not caps.supports_prompt_caching:
        # Provider handles caching automatically (google/openai) or has no
        # portable cache knob (bedrock/voyage) -- no settings to emit.
        return {}
    ttl = spec.caching.ttl  # "5m" | "1h"
    return {
        "anthropic_cache_instructions": ttl,
        "anthropic_cache_tool_definitions": ttl,
    }


def build_model_settings(spec: ModelSpec) -> dict:
    """Build the pydantic-ai model_settings dict from a ModelSpec.

    Resolves capabilities once (pure function over provider+model) and merges:
      spec.settings (temperature, max_tokens, etc.)
      + map_thinking     (capability-driven thinking config)
      + _caching_settings (capability-gated cache control)

    Returns a flat dict suitable for pydantic-ai's model_settings parameter.
    """
    from .capability_resolver import resolve_capabilities
    caps = resolve_capabilities(spec.provider, spec.model)
    settings: dict = dict(spec.settings)
    settings.update(map_thinking(spec.provider, caps, spec.thinking))
    settings.update(_caching_settings(spec, caps))
    return settings


def build_model(
    spec: ModelSpec,
    api_key: str | None = None,
    region: str | None = None,
    base_url: str | None = None,
):
    """Construct a pydantic-ai Model object from a ModelSpec.

    All construction is explicit -- os.environ
    is never read for credentials. The api_key, region, and base_url must be
    passed explicitly (typically from resolve_provider_auth).

    - bedrock: region is REQUIRED; raises AgentError(code='missing_region') when
      absent. api_key is REQUIRED; raises AgentError(code='missing_credentials')
      when absent -- the AWS credential chain is not used. base_url optionally
      overrides the endpoint.
    - google/anthropic/openai: api_key is required; raises
      AgentError(code='missing_credentials') when absent. base_url optionally
      overrides the endpoint (google ignores base_url per scope decision).
    - openrouter: key-requiring; falls through to the key-requiring path below --
      no explicit branch needed. base_url is not threaded (the library fixes
      https://openrouter.ai/api/v1 internally). Model ids are namespaced vendor/model.
    - keyless providers (KEYLESS_PROVIDER_TYPES): base_url is REQUIRED; raises
      AgentError(code='missing_base_url') when absent. A placeholder api_key is
      injected because the OpenAI SDK requires a non-empty string. Never reads the
      credential store. Dormant -- KEYLESS_PROVIDER_TYPES is empty after M3; retained
      for a future local-provider re-add (Decision 1).

    Raises AgentError(code='unknown_provider') for unrecognised providers.
    """
    prefix = _PROVIDER_PREFIX.get(spec.provider)
    if prefix is None:
        raise AgentError(AgentDiagnostic(
            code="unknown_provider",
            agent=spec.provider,
            stage="build_model",
            message=(
                f"Unknown provider '{spec.provider}'. "
                f"Expected one of: {', '.join(sorted(_PROVIDER_PREFIX))}"
            ),
        ))

    from ..types import KEYLESS_PROVIDER_TYPES
    # Dormant keyless-local seam: KEYLESS_PROVIDER_TYPES is empty after M3 so this
    # branch is never reached; retained for a future local-provider re-add (Decision 1).
    if spec.provider in KEYLESS_PROVIDER_TYPES:
        # Keyless providers authenticate via base_url, not a stored secret.
        # base_url must be configured since LOCAL_PROVIDERS is also empty after M3.
        if not base_url:
            raise AgentError(AgentDiagnostic(
                code="missing_base_url",
                agent=spec.provider,
                stage="build_model",
                message=(
                    f"No base_url configured for provider '{spec.provider}'. "
                    f"Set a base_url in provider settings."
                ),
            ))
        return _build_explicit_model(spec, api_key, base_url=base_url)

    if spec.provider == "bedrock":
        # Region is required for bedrock: boto3 has no reliable default and a
        # missing region produces a cryptic NoRegionError deep in the AWS SDK.
        # Failing early with a named diagnostic makes misconfiguration obvious.
        if not region:
            raise AgentError(AgentDiagnostic(
                code="missing_region",
                agent=spec.provider,
                stage="build_model",
                message=(
                    "No region configured for provider 'bedrock'. "
                    "Set a region (e.g. 'us-east-1') in provider settings."
                ),
            ))
        # Bedrock requires an explicit long-lived API key stored in the
        # credential store.  The AWS credential chain is not used: it is
        # unreliable in deployed environments and was rejected by the user.
        if api_key is None:
            raise AgentError(AgentDiagnostic(
                code="missing_credentials",
                agent=spec.provider,
                stage="build_model",
                message=(
                    "No stored API key for provider 'bedrock'. "
                    "Bedrock requires a long-lived API key; "
                    "the AWS credential chain is not used."
                ),
            ))
        return _build_explicit_model(spec, api_key, region=region, base_url=base_url)

    # Key-requiring providers: google, anthropic, openai.
    if api_key is None:
        # Raise rather than fall back to os.environ -- the credential store is
        # the only permitted source; a silent env read would bypass it.
        raise AgentError(AgentDiagnostic(
            code="missing_credentials",
            agent=spec.provider,
            stage="build_model",
            message=(
                f"No stored credential for provider '{spec.provider}'. "
                f"Add the credential via the store before starting a run."
            ),
        ))
    return _build_explicit_model(spec, api_key, base_url=base_url)


def _build_explicit_model(
    spec: ModelSpec,
    api_key: str | None,
    region: str | None = None,
    base_url: str | None = None,
):
    """Build a provider-typed model, threading region and base_url into constructors.

    api_key is required for bedrock (enforced by build_model's missing_credentials
    gate before this is called).  region and base_url are optional for non-bedrock
    providers; base_url is not threaded for google (brief scope) or openrouter
    (the library's OpenRouterProvider fixes the endpoint to https://openrouter.ai/api/v1).
    For keyless providers (KEYLESS_PROVIDER_TYPES), api_key falls back to the
    placeholder 'keyless-local' -- the OpenAI SDK requires a non-empty string.
    openrouter uses namespaced vendor/model ids (e.g. 'anthropic/claude-3.5-sonnet').
    Explicit construction avoids any implicit os.environ reads.
    """
    if spec.provider == "google":
        # Google: no base_url threading per brief decision 5 (scope limited to
        # OpenAI/Anthropic/Bedrock); plain key injection only.
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider
        return GoogleModel(spec.model, provider=GoogleProvider(api_key=api_key))

    if spec.provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
        return AnthropicModel(
            spec.model,
            provider=AnthropicProvider(
                api_key=api_key,
                **({"base_url": base_url} if base_url else {}),
            ),
        )

    if spec.provider == "openai":
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        return OpenAIChatModel(
            spec.model,
            provider=OpenAIProvider(
                api_key=api_key,
                **({"base_url": base_url} if base_url else {}),
            ),
        )

    if spec.provider == "openrouter":
        # OpenRouterProvider fixes the endpoint to https://openrouter.ai/api/v1
        # internally; no base_url threading (Decision 6). api_key is guaranteed
        # non-None by build_model's key-requiring fall-through before this call.
        from pydantic_ai.models.openrouter import OpenRouterModel
        from pydantic_ai.providers.openrouter import OpenRouterProvider
        return OpenRouterModel(
            spec.model,
            provider=OpenRouterProvider(api_key=api_key),
        )

    from ..types import KEYLESS_PROVIDER_TYPES
    # Dormant keyless-local seam: KEYLESS_PROVIDER_TYPES is empty after M3 so this
    # branch is never reached; retained for a future local-provider re-add (Decision 1).
    if spec.provider in KEYLESS_PROVIDER_TYPES:
        # Keyless providers speak the OpenAI protocol via base_url. The OpenAI SDK
        # requires a non-empty api_key string; use a stable placeholder.
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        return OpenAIChatModel(
            spec.model,
            provider=OpenAIProvider(
                api_key=(api_key or "keyless-local"),
                **({"base_url": base_url} if base_url else {}),
            ),
        )

    if spec.provider == "bedrock":
        from pydantic_ai.models.bedrock import BedrockConverseModel
        from pydantic_ai.providers.bedrock import BedrockProvider
        # region and api_key are both guaranteed non-None by build_model's
        # missing_region and missing_credentials gates before this point.
        return BedrockConverseModel(
            spec.model,
            provider=BedrockProvider(
                region_name=region,
                api_key=api_key,
                **({"base_url": base_url} if base_url else {}),
            ),
        )

    # Should not reach here: caller already validated prefix.
    raise AgentError(AgentDiagnostic(
        code="unknown_provider",
        agent=spec.provider,
        stage="build_model",
        message=f"No explicit-model builder for provider '{spec.provider}'",
    ))
