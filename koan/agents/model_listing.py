# Live model-list retrieval for listing-capable providers.
#
# Single responsibility: fetch the provider's current model list and filter it
# to chat/completion models. No caching, no projection coupling, no state mutation.
# Results are returned as ProviderModel instances; the caller decides what to do
# with them (overlay update, Test response, etc.).
#
# Listing-capable providers: openai, anthropic, google, openrouter, ollama-cloud.
# Excluded: bedrock (no list API on the runtime client), voyage (embedding only).
# Keyless providers (KEYLESS_PROVIDER_TYPES) are also listing-capable when
# configured; dormant after M3 since KEYLESS_PROVIDER_TYPES is empty.

from __future__ import annotations

import asyncio
import logging
from ..credentials import CredentialStore
from ..types import Connection, ProviderModel

log = logging.getLogger("koan.model_listing")


class ModelListingError(Exception):
    """Raised when a provider's model-list call fails (network, auth, or parse).

    The message is human-readable and safe to surface in the Test endpoint
    response body. It never contains credentials.
    """


# OpenRouter's base URL mirrors the constant fixed internally by
# pydantic_ai.providers.openrouter.OpenRouterProvider; kept here so the listing
# path does not need to import the provider class at module load time.
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Non-chat model families by id substring, used to filter id-only OpenAI-compatible
# catalogs (openai, openrouter, keyless providers). Checked via substring match so versioned ids
# (e.g. dall-e-3) and slash-prefixed ids (e.g. qwen/qwen3.6) are caught correctly.
_NON_CHAT_ID_SUBSTRINGS = frozenset({
    "embedding",
    "whisper",
    "tts",
    "dall-e",
    "dalle",
    "moderation",
    "image",
    "audio",
    "realtime",
    "transcribe",
})


def _is_chat_model_id(model_id: str) -> bool:
    """Return True when an id-only model id looks like a chat/completion model.

    Used by the openai, openrouter, and keyless-provider listing paths (all receive
    OpenAI-compatible /v1/models responses with no type field). Excludes known
    non-chat families (embeddings, TTS, DALL-E, moderation, etc.) by id substring
    match. False positives are acceptable: this filters for display, not access control.
    """
    lower = model_id.lower()
    return not any(sub in lower for sub in _NON_CHAT_ID_SUBSTRINGS)


async def _list_openai_compatible_models(
    provider: str,
    api_key: str,
    base_url: str | None,
    timeout: float,
) -> list[ProviderModel]:
    """Fetch and filter chat models from any OpenAI-compatible /v1/models endpoint.

    Works for OpenAI proper (provider='openai') and OpenRouter (provider='openrouter',
    base_url=_OPENROUTER_BASE_URL), as well as any future keyless-local provider.
    Stamps the passed provider label onto every returned ProviderModel -- callers must
    pass the correct label since the overlay and per-connection family derivation in
    app.py key on it.

    api_key must be a non-empty string; keyless callers should pass the placeholder
    'keyless-local' rather than an empty string (the OpenAI SDK rejects empty keys).
    Raises ModelListingError on any network, auth, or parse failure.
    """
    try:
        from openai import AsyncOpenAI
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = AsyncOpenAI(**kwargs)
        async with asyncio.timeout(timeout):
            response = await client.models.list()
        return [
            ProviderModel(
                provider=provider,
                model=m.id,
                display_name=m.id,
            )
            for m in response.data
            if _is_chat_model_id(m.id)
        ]
    except Exception as exc:
        raise ModelListingError(str(exc)) from exc


async def _list_anthropic_models(
    api_key: str,
    timeout: float,
) -> list[ProviderModel]:
    """Fetch Anthropic chat models.

    Anthropic's list endpoint returns chat models only, so no extra filtering
    is needed. Raises ModelListingError on any failure.
    """
    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=api_key)
        async with asyncio.timeout(timeout):
            response = await client.models.list()
        return [
            ProviderModel(
                provider="anthropic",
                model=m.id,
                display_name=getattr(m, "display_name", None) or m.id,
            )
            for m in response.data
        ]
    except Exception as exc:
        raise ModelListingError(str(exc)) from exc


async def _list_google_models(
    api_key: str,
    timeout: float,
) -> list[ProviderModel]:
    """Fetch Google generative AI models that support generateContent (chat).

    Filters by 'generateContent' in supported_actions so embedding-only models
    are excluded. Strips the leading 'models/' prefix from the id. Raises
    ModelListingError on any failure.
    """
    try:
        import google.genai as genai
        client = genai.Client(api_key=api_key)
        async with asyncio.timeout(timeout):
            models = [m async for m in await client.aio.models.list()]
        result = []
        for m in models:
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" not in actions:
                continue
            model_id = (m.name or "").removeprefix("models/")
            if not model_id:
                continue
            display = getattr(m, "display_name", None) or model_id
            result.append(ProviderModel(
                provider="google",
                model=model_id,
                display_name=display,
            ))
        return result
    except Exception as exc:
        raise ModelListingError(str(exc)) from exc


async def list_provider_models(
    provider: str,
    *,
    api_key: str | None,
    base_url: str | None,
    region: str | None = None,
    timeout: float = 8.0,
) -> list[ProviderModel]:
    """Retrieve and filter the live model list for a listing-capable provider.

    Dispatches to the per-provider helper based on provider. Raises
    ModelListingError for any unsupported provider (e.g. bedrock, voyage) or
    when the underlying call fails (network, auth, parse). The timeout applies
    to the entire network round-trip; an unreachable provider raises within that
    window rather than blocking indefinitely.

    openai delegates to _list_openai_compatible_models (the OpenAI-compat /v1/models
    path). anthropic and google have their own listing paths. openrouter delegates to
    _list_openai_compatible_models with the library-fixed _OPENROUTER_BASE_URL; the
    incoming base_url is ignored (openrouter's endpoint is fixed by the library).
    ollama-cloud delegates to _list_openai_compatible_models with OLLAMA_CLOUD_BASE_URL;
    the incoming base_url is intentionally ignored (fixed cloud endpoint, brief D7).
    Keyless providers (KEYLESS_PROVIDER_TYPES) also use _list_openai_compatible_models
    with a configured base_url; dormant after M3 since KEYLESS_PROVIDER_TYPES is empty.

    Listing-capable: openai, anthropic, google, openrouter, ollama-cloud.
    Not supported: bedrock (no runtime list API), voyage (embedding-only).
    """
    if provider == "openai":
        if not api_key:
            raise ModelListingError("no api_key provided for openai")
        return await _list_openai_compatible_models("openai", api_key, base_url, timeout)

    if provider == "anthropic":
        if not api_key:
            raise ModelListingError("no api_key provided for anthropic")
        return await _list_anthropic_models(api_key, timeout)

    if provider == "google":
        if not api_key:
            raise ModelListingError("no api_key provided for google")
        return await _list_google_models(api_key, timeout)

    from ..types import KEYLESS_PROVIDER_TYPES
    from ..credentials import LOCAL_PROVIDERS
    # Dormant keyless-local seam: KEYLESS_PROVIDER_TYPES is empty after M3 so this
    # branch is never reached; retained for a future local-provider re-add (Decision 1).
    if provider in KEYLESS_PROVIDER_TYPES:
        # Keyless providers speak the OpenAI protocol via a configured base_url.
        # LOCAL_PROVIDERS is also empty after M3, so base_url must be configured.
        # The "keyless-local" placeholder mirrors adapter._build_explicit_model.
        effective_url = base_url or LOCAL_PROVIDERS.get(provider)
        return await _list_openai_compatible_models(
            provider, api_key or "keyless-local", effective_url, timeout
        )

    if provider == "openrouter":
        # openrouter is key-required; endpoint is fixed by the library (Decision 6).
        # The incoming base_url is intentionally ignored: openrouter's URL is not
        # user-configurable, so passing it through would be misleading.
        if not api_key:
            raise ModelListingError("no api_key provided for openrouter")
        return await _list_openai_compatible_models(
            "openrouter", api_key, _OPENROUTER_BASE_URL, timeout
        )

    if provider == "ollama-cloud":
        # Key-required; endpoint is fixed to the cloud URL (brief D7). The incoming
        # base_url is intentionally ignored. Reuses the shared OpenAI-compatible
        # /v1/models listing path (Ollama Cloud exposes a /v1/models endpoint).
        if not api_key:
            raise ModelListingError("no api_key provided for ollama-cloud")
        from koan.models.routes import get_route
        ollama_endpoint = get_route("ollama-cloud").endpoint_template
        return await _list_openai_compatible_models(
            "ollama-cloud", api_key, ollama_endpoint, timeout
        )

    raise ModelListingError(
        f"provider '{provider}' does not support model listing "
        f"(supported: openai, anthropic, google, openrouter, ollama-cloud)"
    )


async def list_models_for_connection(
    connection: Connection,
    store: CredentialStore | None,
    timeout: float = 8.0,
) -> list[ProviderModel]:
    """Retrieve the live model list for a connection, resolving auth from the store.

    Wraps list_provider_models with connection-keyed credential resolution:
    decrypts api_key from the store by connection.id, threads region and base_url
    from the Connection, then dispatches to list_provider_models(connection.type).

    For listing-capable types (openai, anthropic, google, openrouter, ollama-cloud) this
    returns the provider's live model list. For non-listing types (bedrock, voyage) or on
    any network/auth failure, ModelListingError is raised -- the caller treats this
    as "listing unavailable; fall back to free-text entry."

    The static model_registry is NOT consulted or merged here (brief D7: the
    selectable list is the live provider response only).
    """
    # Import here to avoid a circular dependency at module load time;
    # adapter.py imports from types.py, not from model_listing.py.
    from .adapter import resolve_provider_auth
    resolved = resolve_provider_auth(connection, store)
    return await list_provider_models(
        connection.type,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
        region=resolved.region,
        timeout=timeout,
    )
