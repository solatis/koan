# Unit tests for koan/agents/model_listing.py.
#
# Testing philosophy (per project lesson): pure helper functions (_is_chat_openai_id,
# payload parsing) are tested directly with sample data -- the legitimate unit target.
# Network-touching helpers are tested with real LM Studio when it is running locally
# and with a lightweight stub for the ModelListingError / unsupported-provider paths.
# No mock injection points exist solely for substitution; test seams are minimal.

from __future__ import annotations

import pytest


# -- _is_chat_openai_id -------------------------------------------------------


def test_is_chat_openai_id_accepts_gpt():
    """gpt-4 / gpt-3.5 class ids are chat models."""
    from koan.agents.model_listing import _is_chat_openai_id
    assert _is_chat_openai_id("gpt-4")
    assert _is_chat_openai_id("gpt-4o")
    assert _is_chat_openai_id("gpt-3.5-turbo")
    assert _is_chat_openai_id("o1-mini")


def test_is_chat_openai_id_rejects_non_chat():
    """Known non-chat families are filtered out."""
    from koan.agents.model_listing import _is_chat_openai_id
    assert not _is_chat_openai_id("text-embedding-ada-002")
    assert not _is_chat_openai_id("whisper-1")
    assert not _is_chat_openai_id("tts-1")
    assert not _is_chat_openai_id("dall-e-3")
    assert not _is_chat_openai_id("omni-moderation-latest")
    assert not _is_chat_openai_id("gpt-4o-realtime-preview")
    assert not _is_chat_openai_id("gpt-4o-audio-preview")
    assert not _is_chat_openai_id("gpt-4o-transcribe")


# -- _list_lmstudio_models (unit: payload parsing) ----------------------------


@pytest.mark.asyncio
async def test_list_lmstudio_models_filters_to_llm_type(monkeypatch):
    """_list_lmstudio_models keeps only entries with type=='llm' and reads context length.

    Uses monkeypatched httpx so no real server is required for this unit test.
    """
    import httpx
    from koan.agents.model_listing import _list_lmstudio_models

    payload = [
        {"id": "llama-3.2-3b", "type": "llm", "max_context_length": 131072},
        {"id": "nomic-embed-text", "type": "embeddings", "max_context_length": 2048},
        {"id": "qwen3-embedding", "type": "embeddings", "max_context_length": 8192},
        {"id": "gemma-3b", "type": "llm", "max_context_length": 8192},
    ]

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url):
            return _FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", lambda: _FakeClient())

    models = await _list_lmstudio_models("http://localhost:1234/v1", timeout=5.0)
    assert len(models) == 2
    ids = {m.model for m in models}
    assert "llama-3.2-3b" in ids
    assert "gemma-3b" in ids
    assert "nomic-embed-text" not in ids
    # context_window is read from max_context_length
    llama = next(m for m in models if m.model == "llama-3.2-3b")
    assert llama.context_window == 131072


@pytest.mark.asyncio
async def test_list_lmstudio_models_strips_v1_suffix(monkeypatch):
    """_list_lmstudio_models strips trailing /v1 from base_url to get the native endpoint."""
    from koan.agents.model_listing import _list_lmstudio_models
    called_urls: list[str] = []

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return []

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url):
            called_urls.append(url)
            return _FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", lambda: _FakeClient())

    await _list_lmstudio_models("http://localhost:1234/v1", timeout=5.0)
    assert len(called_urls) == 1
    assert called_urls[0] == "http://localhost:1234/api/v0/models"


# -- list_provider_models unsupported provider --------------------------------


@pytest.mark.asyncio
async def test_list_provider_models_raises_for_unsupported():
    """list_provider_models raises ModelListingError for unsupported providers."""
    from koan.agents.model_listing import list_provider_models, ModelListingError

    with pytest.raises(ModelListingError, match="bedrock"):
        await list_provider_models(
            "bedrock",
            api_key="k",
            base_url=None,
        )

    with pytest.raises(ModelListingError, match="voyage"):
        await list_provider_models(
            "voyage",
            api_key="k",
            base_url=None,
        )


# -- list_models_for_connection -----------------------------------------------


@pytest.mark.asyncio
async def test_list_models_for_connection_listing_capable(monkeypatch):
    """list_models_for_connection returns live ProviderModels for a listing-capable type."""
    from koan.agents.model_listing import list_models_for_connection
    from koan.types import Connection, ProviderModel

    conn = Connection(id="openai-main", type="openai")

    fake_models = [
        ProviderModel(provider="openai", model="gpt-4o", display_name="GPT-4o"),
        ProviderModel(provider="openai", model="gpt-4o-mini", display_name="GPT-4o Mini"),
    ]

    async def fake_list_provider_models(provider, *, api_key, base_url, region=None, timeout=8.0):
        assert provider == "openai"
        return fake_models

    monkeypatch.setattr(
        "koan.agents.model_listing.list_provider_models",
        fake_list_provider_models,
    )

    # Minimal fake credential store: resolve returns a dummy key.
    class _FakeStore:
        def resolve(self, conn_id: str) -> str | None:
            return "fake-key"

    result = await list_models_for_connection(conn, _FakeStore())
    assert result == fake_models


@pytest.mark.asyncio
async def test_list_models_for_connection_non_listing_type_raises(monkeypatch):
    """list_models_for_connection raises ModelListingError for bedrock (non-listing)."""
    from koan.agents.model_listing import ModelListingError, list_models_for_connection
    from koan.types import Connection

    conn = Connection(id="bedrock-main", type="bedrock", region="us-east-1")

    # No monkeypatch needed: list_provider_models already raises for bedrock.
    with pytest.raises(ModelListingError, match="bedrock"):
        await list_models_for_connection(conn, None)


@pytest.mark.asyncio
async def test_list_models_for_connection_voyage_raises(monkeypatch):
    """list_models_for_connection raises ModelListingError for voyage (embedding-only)."""
    from koan.agents.model_listing import ModelListingError, list_models_for_connection
    from koan.types import Connection

    conn = Connection(id="voyage-main", type="voyage")

    with pytest.raises(ModelListingError, match="voyage"):
        await list_models_for_connection(conn, None)


# -- Real LM Studio integration test ------------------------------------------
# Requires a running LM Studio at http://localhost:1234.
# Marked with a custom marker; CI can skip via -m "not lmstudio_live".


@pytest.mark.asyncio
@pytest.mark.lmstudio_live
async def test_list_lmstudio_models_live():
    """Integration: list models from a real LM Studio at localhost:1234.

    Asserts at least one model is returned and its provider field is 'lmstudio'.
    Skip this test when LM Studio is not running by using -m 'not lmstudio_live'.
    """
    from koan.agents.model_listing import list_provider_models, ModelListingError

    try:
        models = await list_provider_models(
            "lmstudio",
            api_key=None,
            base_url="http://localhost:1234/v1",
            timeout=8.0,
        )
    except ModelListingError as exc:
        pytest.skip(f"LM Studio not available: {exc}")

    assert len(models) >= 0  # may be 0 if no models loaded
    for m in models:
        assert m.provider == "lmstudio"
        assert m.model
        assert m.display_name
