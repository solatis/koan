# Live model-list retrieval for listing-capable providers.
#
# Single responsibility: fetch the provider's current model list and filter it
# to chat/completion models. No caching, no projection coupling, no state mutation.
# Results are returned as ProviderModel instances; the caller decides what to do
# with them (overlay update, Test response, etc.).
#
# Listing-capable providers: lmstudio, openai, anthropic, google.
# Excluded: bedrock (no list API on the runtime client), voyage (embedding only).

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ..types import ProviderModel

if TYPE_CHECKING:
    from ..credentials import CredentialStore
    from ..types import Connection

log = logging.getLogger("koan.model_listing")


class ModelListingError(Exception):
    """Raised when a provider's model-list call fails (network, auth, or parse).

    The message is human-readable and safe to surface in the Test endpoint
    response body. It never contains credentials.
    """


# Non-chat model families by id substring, used to filter OpenAI's heterogeneous
# catalog. Checked via substring match so versioned ids (e.g. dall-e-3) are caught.
_OPENAI_NON_CHAT_SUBSTRINGS = frozenset({
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


def _is_chat_openai_id(model_id: str) -> bool:
    """Return True when a model id looks like a chat/completion model.

    Excludes known non-chat families (embeddings, TTS, DALL-E, moderation, etc.)
    by substring match. False positives (a future OpenAI model whose id contains
    'audio' but is a chat model) are acceptable: the list is used for display
    filtering, not access control.
    """
    lower = model_id.lower()
    return not any(sub in lower for sub in _OPENAI_NON_CHAT_SUBSTRINGS)


async def _list_openai_models(
    api_key: str,
    base_url: str | None,
    timeout: float,
) -> list[ProviderModel]:
    """Fetch and filter OpenAI (or compatible) chat models.

    Constructs AsyncOpenAI with the given credentials, lists all models, and
    keeps only those whose id passes _is_chat_openai_id. Raises ModelListingError
    on any network, auth, or unexpected parse failure.
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
                provider="openai",
                model=m.id,
                display_name=m.id,
                context_window=0,
            )
            for m in response.data
            if _is_chat_openai_id(m.id)
        ]
    except Exception as exc:
        raise ModelListingError(str(exc)) from exc


async def _list_anthropic_models(
    api_key: str,
    timeout: float,
) -> list[ProviderModel]:
    """Fetch Anthropic chat models.

    Anthropic's list endpoint returns chat models only, so no extra filtering
    is needed. context_window is read from max_input_tokens when available.
    Raises ModelListingError on any failure.
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
                context_window=getattr(m, "max_input_tokens", 0) or 0,
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
            ctx = getattr(m, "input_token_limit", None) or 0
            result.append(ProviderModel(
                provider="google",
                model=model_id,
                display_name=display,
                context_window=ctx,
            ))
        return result
    except Exception as exc:
        raise ModelListingError(str(exc)) from exc


async def _list_lmstudio_models(
    base_url: str,
    timeout: float,
) -> list[ProviderModel]:
    """Fetch LM Studio models via the native /api/v0/models endpoint.

    Uses LM Studio's own API (not the OpenAI-compat /v1/models) because it
    exposes 'type' and 'max_context_length', letting us filter to llm-type
    models and read context windows accurately. The base_url is expected to be
    the OpenAI-compat root (e.g. http://localhost:1234/v1); '/v1' is stripped to
    get the host root for the native endpoint. Raises ModelListingError on failure.
    """
    try:
        import httpx
        # Strip trailing /v1 suffix to get the host root for the native endpoint.
        root = base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        url = f"{root}/api/v0/models"
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient() as http:
                resp = await http.get(url)
        resp.raise_for_status()
        data = resp.json()
        entries = data if isinstance(data, list) else data.get("data", [])
        return [
            ProviderModel(
                provider="lmstudio",
                model=entry["id"],
                display_name=entry["id"],
                context_window=entry.get("max_context_length", 0) or 0,
            )
            for entry in entries
            if isinstance(entry, dict) and entry.get("type") == "llm"
        ]
    except ModelListingError:
        raise
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

    Listing-capable: lmstudio, openai, anthropic, google.
    Not supported: bedrock (no runtime list API), voyage (embedding-only).
    """
    if provider == "openai":
        if not api_key:
            raise ModelListingError("no api_key provided for openai")
        return await _list_openai_models(api_key, base_url, timeout)

    if provider == "anthropic":
        if not api_key:
            raise ModelListingError("no api_key provided for anthropic")
        return await _list_anthropic_models(api_key, timeout)

    if provider == "google":
        if not api_key:
            raise ModelListingError("no api_key provided for google")
        return await _list_google_models(api_key, timeout)

    if provider == "lmstudio":
        # base_url defaults to the LOCAL_PROVIDERS value when absent; we still
        # require the caller to resolve it so this function stays stateless.
        effective_url = base_url or "http://localhost:1234/v1"
        return await _list_lmstudio_models(effective_url, timeout)

    raise ModelListingError(
        f"provider '{provider}' does not support model listing "
        f"(supported: openai, anthropic, google, lmstudio)"
    )


async def list_models_for_connection(
    connection: "Connection",
    store: "CredentialStore | None",
    timeout: float = 8.0,
) -> list[ProviderModel]:
    """Retrieve the live model list for a connection, resolving auth from the store.

    Wraps list_provider_models with connection-keyed credential resolution:
    decrypts api_key from the store by connection.id, threads region and base_url
    from the Connection, then dispatches to list_provider_models(connection.type).

    For listing-capable types (openai, anthropic, google, lmstudio) this returns
    the provider's live model list. For non-listing types (bedrock, voyage) or
    on any network/auth failure, ModelListingError is raised -- the caller treats
    this as "listing unavailable; fall back to free-text entry."

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
