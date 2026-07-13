# Provider adapter: the single per-provider dialect seam.
# Covers all day-one providers (M7): google, anthropic, openai, bedrock.
# Built against the installed pydantic-ai 2.0.0 API.
#
# Responsibilities:
#   - provider_available: check credential presence in CredentialStore
#   - build_model_settings: return pre-baked settings from a ModelSpec
#   - build_usage_limits: shared usage-limits policy
#   - build_model: construct a pydantic-ai Model object from a ModelSpec +
#     an explicit api_key (never reads os.environ)
#
# M2: map_thinking, _caching_settings, _THINKING_BUDGET, _OPENAI_EFFORT,
# _PROVIDER_PREFIX, _KEY_REQUIRING_PROVIDERS, OLLAMA_CLOUD_BASE_URL, and
# cache_ttl_for/_CACHE_TIER_TTL are all deleted. Thinking is now a passthrough
# via apply_thinking (dialects.py); cache settings via emit_cache_settings
# (dialects.py); cache_ttl_for relocated to dialects.py. build_model dispatches
# on spec.offering.route.dialect instead of spec.provider string comparisons.

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic_ai.usage import UsageLimits

from ..agents.base import AgentDiagnostic, AgentError
from ..types import CachingPolicy, Connection, ModelSpec

if TYPE_CHECKING:
    from ..credentials import CredentialStore


@dataclass
class ResolvedProviderAuth:
    """In-memory join of a provider's decrypted secret and its non-secret settings.

    Produced by resolve_provider_auth; consumed by build_model. Never persisted
    or transmitted -- it exists only for the duration of a model-build call.
    """

    api_key: str | None
    region: str | None
    base_url: str | None


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
    region (locality) and base_url come directly from the Connection fields.
    Returns None for each absent value; never raises on missing data.
    connection may be None for pre-M1 ModelSpecs (no connection_id); all
    fields return None in that case.
    """
    if connection is None:
        return ResolvedProviderAuth(api_key=None, region=None, base_url=None)
    api_key = store.resolve(connection.id) if store else None
    return ResolvedProviderAuth(
        api_key=api_key,
        region=connection.locality,
        base_url=connection.base_url,
    )


def build_model_settings(spec: ModelSpec) -> dict:
    """Return the pre-baked model_settings dict from a ModelSpec.

    Thinking and caching settings are baked into spec.settings at flatten time
    (by build_resolved_model in registry.py), so this is now a trivial pass-through.
    Keeping the function signature stable avoids changes in every caller.

    Returns a flat dict suitable for pydantic-ai's model_settings parameter.
    """
    return dict(spec.settings)


def build_usage_limits() -> UsageLimits:
    """Return the shared usage-limits policy for all koan agent invocations.

    Sets request_limit=None to disable pydantic_ai's default cap of 50 model
    requests per agent run. That default fails fast with no recovery path
    (classify_provider_error treats UsageLimitExceeded as 'unexpected'); removing
    it lets long-running orchestrator and scout loops complete naturally. All other
    UsageLimits fields (input_tokens_limit, output_tokens_limit, total_tokens_limit,
    tool_calls_limit) remain at their None defaults (disabled). This is the single
    chokepoint for the usage-limits policy -- no call site inlines UsageLimits.
    Note: koan_reflect retains its own independent max_iterations cap separately.
    """
    return UsageLimits(request_limit=None)


def build_model(
    spec: ModelSpec,
    api_key: str | None = None,
    region: str | None = None,
    base_url: str | None = None,
):
    """Construct a pydantic-ai Model object from a ModelSpec.

    M2: dispatches on ``spec.offering.route.dialect`` instead of ``spec.provider``
    string comparisons. The ``region`` parameter (if provided) overrides the
    offering's locality; when None, the offering's locality is used. All
    construction is explicit -- os.environ is never read for credentials.

    Raises AgentError(code='unknown_provider') when the spec has no offering or
    the dialect has no explicit-model builder. Raises
    AgentError(code='missing_region') for bedrock-converse without a region, and
    for any route whose endpoint_template contains {region} but no locality is set.
    Raises AgentError(code='missing_credentials') when api_key is required but
    absent.
    """
    offering = spec.offering
    if offering is None:
        raise AgentError(AgentDiagnostic(
            code="unknown_provider",
            agent="",
            stage="build_model",
            message="ModelSpec has no offering -- was build_resolved_model called?",
        ))

    route = offering.route
    dialect = route.dialect

    # Resolve effective region/locality from the offering.
    effective_region = region or offering.locality
    # Construct base_url from route endpoint_template when not explicitly set
    # on the connection. Generic plumbing: any route with {region} in its
    # endpoint_template gets the locality substituted. Not dialect code (Decision 4) --
    # checks template content, not route ID. bedrock-converse has endpoint_template=None
    # so it is unaffected; ollama-cloud's template lacks {region}.
    if base_url is None and route.endpoint_template and "{region}" in route.endpoint_template:
        if not effective_region:
            raise AgentError(AgentDiagnostic(
                code="missing_region",
                agent=route.id,
                stage="build_model",
                message=f"No locality configured for route '{route.id}'. The endpoint template requires a region.",
            ))
        base_url = route.endpoint_template.replace("{region}", effective_region)

    if dialect == "bedrock-converse":
        if not effective_region:
            raise AgentError(AgentDiagnostic(
                code="missing_region",
                agent=route.id,
                stage="build_model",
                message="No region configured for bedrock-converse. Set a locality on the connection.",
            ))
        if api_key is None:
            raise AgentError(AgentDiagnostic(
                code="missing_credentials",
                agent=route.id,
                stage="build_model",
                message="No stored API key for bedrock-converse.",
            ))
        return _build_explicit_model(spec, api_key, region=effective_region, base_url=base_url)

    # Key-requiring dialects: anthropic-messages, openai-chat, google-genai
    if api_key is None:
        raise AgentError(AgentDiagnostic(
            code="missing_credentials",
            agent=route.id,
            stage="build_model",
            message=f"No stored credential for route '{route.id}'.",
        ))
    return _build_explicit_model(spec, api_key, base_url=base_url)


def _build_explicit_model(
    spec: ModelSpec,
    api_key: str | None,
    region: str | None = None,
    base_url: str | None = None,
):
    """Build a provider-typed model, threading region and base_url into constructors.

    Dispatches on ``spec.offering.route.dialect``. The openai-chat dialect covers
    openai, openrouter, and ollama-cloud (all OpenAI-protocol); openrouter uses
    OpenRouterProvider (library-fixed endpoint); ollama-cloud uses OllamaProvider
    with the route's endpoint_template. For keyless providers
    (KEYLESS_PROVIDER_TYPES), api_key falls back to the placeholder 'keyless-local'
    -- the OpenAI SDK requires a non-empty string. Explicit construction avoids
    any implicit os.environ reads.
    """
    dialect = spec.offering.route.dialect

    if dialect == "google-genai":
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider
        return GoogleModel(spec.model, provider=GoogleProvider(api_key=api_key))

    if dialect == "anthropic-messages":
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
        return AnthropicModel(
            spec.model,
            provider=AnthropicProvider(
                api_key=api_key,
                **({"base_url": base_url} if base_url else {}),
            ),
        )

    if dialect == "openai-chat":
        # Covers openai, openrouter, ollama-cloud -- all use OpenAI-protocol.
        route = spec.offering.route
        if route.id == "openrouter":
            from pydantic_ai.models.openrouter import OpenRouterModel
            from pydantic_ai.providers.openrouter import OpenRouterProvider
            return OpenRouterModel(spec.model, provider=OpenRouterProvider(api_key=api_key))
        if route.id == "ollama-cloud":
            from pydantic_ai.models.ollama import OllamaModel
            from pydantic_ai.providers.ollama import OllamaProvider
            return OllamaModel(
                spec.model,
                provider=OllamaProvider(base_url=route.endpoint_template, api_key=api_key),
            )
        # Default: plain OpenAI
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        return OpenAIChatModel(
            spec.model,
            provider=OpenAIProvider(
                api_key=api_key,
                **({"base_url": base_url} if base_url else {}),
            ),
        )

    if dialect == "bedrock-converse":
        from pydantic_ai.models.bedrock import BedrockConverseModel
        from pydantic_ai.providers.bedrock import BedrockProvider
        return BedrockConverseModel(
            spec.model,
            provider=BedrockProvider(
                api_key=api_key,
                region_name=region,
                **({"base_url": base_url} if base_url else {}),
            ),
        )

    # KEYLESS_PROVIDER_TYPES dormant seam -- keep the fallback for future local-provider re-add.
    from ..types import KEYLESS_PROVIDER_TYPES
    if spec.offering.route.id in KEYLESS_PROVIDER_TYPES:
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        return OpenAIChatModel(
            spec.model,
            provider=OpenAIProvider(
                api_key=(api_key or "keyless-local"),
                **({"base_url": base_url} if base_url else {}),
            ),
        )

    raise AgentError(AgentDiagnostic(
        code="unknown_provider",
        agent=spec.offering.route.id,
        stage="build_model",
        message=f"No explicit-model builder for dialect '{dialect}' (route '{spec.offering.route.id}')",
    ))