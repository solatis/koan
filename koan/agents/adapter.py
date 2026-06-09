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
# lmstudio is the keyless OpenAI-compatible local provider; it reuses the openai build
# path with a placeholder api_key and a configurable base_url.
_PROVIDER_PREFIX: dict[str, str] = {
    "google":    "google",
    "anthropic": "anthropic",
    "openai":    "openai",
    "bedrock":   "bedrock",
    "lmstudio":  "lmstudio",
}

# Providers that require an explicit API key (as opposed to bedrock which
# can authenticate via AWS profile/SSO without a bearer token).
# When api_key is None for a key-requiring provider, build_model raises
# missing_credentials rather than silently falling back to os.environ.
_KEY_REQUIRING_PROVIDERS = {"google", "anthropic", "openai"}


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
    - lmstudio:  no-op (local server; no thinking knob).
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

    if provider in ("bedrock", "lmstudio"):
        # Bedrock: thinking controlled by the underlying model profile inside
        # pydantic_ai's BedrockConverseModel; no portable koan-level knob.
        # lmstudio: local OpenAI-compatible server; no thinking knob exposed.
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
        # portable cache knob (bedrock/lmstudio/voyage) -- no settings to emit.
        return {}
    ttl = spec.caching.ttl  # "5m" | "1h"
    return {
        "anthropic_cache_instructions": ttl,
        "anthropic_cache_tool_definitions": ttl,
    }


def _context_variant_settings(spec: ModelSpec, caps: "ResolvedCapabilities") -> dict:
    """Return provider-specific opt-in settings when a context-window variant is selected.

    When spec.context_window is set to a variant advertised in
    caps.context_window_variants (a window larger than the base caps.context_window),
    this function should emit the provider-specific opt-in (e.g. an Anthropic beta
    header via the anthropic_betas model setting).

    For the current installed pydantic_ai version no clean beta-name constant is
    bundled for the 1M-context opt-in, so this logs a warning and returns {} rather
    than failing the model build (brief D5 / plan constraint).  The variant remains
    advertised in ResolvedCapabilities; the user sees the option but the header is
    not applied until the beta string is confirmed.
    """
    if (
        spec.context_window
        and caps.context_window_variants
        and spec.context_window in caps.context_window_variants
        and spec.context_window > caps.context_window
    ):
        # A variant window is selected.  Log and return {} until the exact
        # provider beta string is confirmed in the deployed pydantic_ai package.
        # When the string is known, emit {"anthropic_betas": ["<beta-name>"]}
        # or the equivalent for other providers.
        from ..logger import get_logger
        _log = get_logger("adapter")
        _log.warning(
            "context-window variant %d selected for %s/%s but no beta opt-in "
            "is configured for the installed pydantic_ai -- variant not applied",
            spec.context_window, spec.provider, spec.model,
        )
    return {}


def build_model_settings(spec: ModelSpec) -> dict:
    """Build the pydantic-ai model_settings dict from a ModelSpec.

    Resolves capabilities once (pure function over provider+model) and merges:
      spec.settings (temperature, max_tokens, etc.)
      + map_thinking     (capability-driven thinking config)
      + _caching_settings (capability-gated cache control)
      + _context_variant_settings (opt-in for selected context-window variants)

    Returns a flat dict suitable for pydantic-ai's model_settings parameter.
    """
    from .capability_resolver import resolve_capabilities
    caps = resolve_capabilities(spec.provider, spec.model)
    settings: dict = dict(spec.settings)
    settings.update(map_thinking(spec.provider, caps, spec.thinking))
    settings.update(_caching_settings(spec, caps))
    settings.update(_context_variant_settings(spec, caps))
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
      absent. api_key is optional -- when absent, boto3 resolves AWS credentials
      via its default chain (keyless-with-region path). base_url optionally
      overrides the endpoint.
    - google/anthropic/openai: api_key is required; raises
      AgentError(code='missing_credentials') when absent. base_url optionally
      overrides the endpoint (google ignores base_url per scope decision).
    - lmstudio: keyless; base_url is REQUIRED; raises
      AgentError(code='missing_base_url') when absent. A placeholder api_key is
      injected because the OpenAI SDK requires a non-empty string even though
      LM Studio ignores it. Never reads the credential store.

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

    if spec.provider == "lmstudio":
        # LM Studio is keyless: api_key is a non-empty placeholder (the OpenAI SDK
        # requires a non-empty string even though LM Studio ignores it). base_url
        # must be configured since there is no global default at build time.
        if not base_url:
            raise AgentError(AgentDiagnostic(
                code="missing_base_url",
                agent=spec.provider,
                stage="build_model",
                message=(
                    "No base_url configured for provider 'lmstudio'. "
                    "Set a base_url (e.g. 'http://localhost:1234/v1') in provider settings."
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

    api_key may be None for bedrock (boto3 resolves AWS credentials via its
    default chain when a region is supplied). region and base_url are optional
    for non-bedrock providers; base_url is not threaded for google (brief scope).
    For lmstudio, api_key falls back to the placeholder 'lm-studio' -- the OpenAI
    SDK requires a non-empty string even though LM Studio ignores it.
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

    if spec.provider == "lmstudio":
        # LM Studio speaks the OpenAI protocol via base_url. The OpenAI SDK requires
        # a non-empty api_key string even when the server ignores it; use a stable
        # placeholder so tests can assert the key value without depending on config.
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        return OpenAIChatModel(
            spec.model,
            provider=OpenAIProvider(
                api_key=(api_key or "lm-studio"),
                **({"base_url": base_url} if base_url else {}),
            ),
        )

    if spec.provider == "bedrock":
        from pydantic_ai.models.bedrock import BedrockConverseModel
        from pydantic_ai.providers.bedrock import BedrockProvider
        # region is guaranteed non-None by build_model's missing_region gate.
        # api_key is optional: omit rather than pass None so boto3 resolves
        # credentials via its default chain when no bearer token is stored.
        return BedrockConverseModel(
            spec.model,
            provider=BedrockProvider(
                region_name=region,
                **({"api_key": api_key} if api_key else {}),
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
